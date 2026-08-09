"""Per-user recommendation orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable

from dotenv import load_dotenv

from heated_topics_v3.clock import SHANGHAI
from heated_topics_v3.contracts import HotItem, ItemDetail
from heated_topics_v3.openbiliclaw_integration import (
    candidate_adapter,
    keyword_extractor,
    last30days_adapter,
    last30days_source,
    body_enricher,
    runtime,
    user_profile,
)

logger = logging.getLogger(__name__)


# Re-export for convenience so tests can patch via `recommender.load_users`.
load_users = user_profile.load_users
# Re-export keyword_extractor entry point so tests can patch via
# `recommender.extract_or_load` (mirrors how the function is called below).
extract_or_load = keyword_extractor.extract_or_load


# Default provider list (ordered by typical relevance for V3 hot topics).
# ``dailyhot:<route>`` syntax dispatches to DailyHotApiProvider — e.g.
# ``dailyhot:36kr`` for 36氪, ``dailyhot:sspai`` for 少数派. Hot-list data
# comes from data/cache/dailyhot/*.json (written by the upstream dailyhot
# client); article bodies are fetched per-URL via GNE.
_DEFAULT_PROVIDERS: tuple[str, ...] = (
    "toutiao",
    "juejin",
    "zhihu_daily",
    "netease_news",
    "sina_news",
    "thepaper",
    "zhihu_hot",
)


# Detail fetch cap per platform: collecting full bodies for 50 items is too
# slow and blocks the hot list. We only need bodies for the candidates the
# engine actually considers.
_DETAIL_FETCH_CAP = 20
# Toutiao's detail fetcher runs Playwright to render article pages. Fetch the
# complete hot board (normally 50 items) so hot-list matching has real article
# text instead of only title/summary fallbacks.
_DETAIL_FETCH_CAP_BY_PLATFORM: dict[str, int] = {
    "toutiao": 50,
}


# Search-enabled providers (no API key required, returns content actually
# matching a keyword — not just whatever is on the hot board today). Order
# matters only for tie-breaks. ``baidu_hot``, ``zhihu_hot`` need credentials;
# ``sina_news`` returns malformed search payloads and was removed (v2.1.4).
_SEARCH_PROVIDERS: tuple[str, ...] = (
    "toutiao",
    "netease_news",
    "sina_news",
    "thepaper",
    "zhihu_daily",
)

# Prefer sources that consistently expose article bodies. Fallback sources
# remain eligible, but are appended after stable article providers.
_ARTICLE_SOURCE_PRIORITY: dict[str, int] = {
    "toutiao": 0,
    "juejin": 1,
    "zhihu_daily": 2,
    "netease_news": 3,
    "sina_news": 4,
    "thepaper": 5,
    "zhihu_hot": 10,
    "baidu": 20,
    "wechat": 21,
}
_NON_ARTICLE_TYPES = frozenset({
    "video", "short_video", "live", "post", "discussion", "question",
    "social_post", "动态",
})

# Per user: take the top-K interests (by weight) and search each on each
# search-enabled provider. 3 × 3 = 9 (provider, interest) pairs; with
# 5 results each = up to 45 search candidates per user. After URL-dedup
# against ~250 hot-list candidates this typically lands around 60-90
# unique items, well within the engine's filter budget.
_SEARCH_TOP_K_INTERESTS = 3
_SEARCH_RESULTS_PER_INTEREST = 5
# Full-body fetches are slow (HTTP + GNE per article). Cap per
# (provider, interest) pair so total stays bounded: 3 × 3 × 3 = 27 fetches
# per user worst case.
_SEARCH_DETAIL_FETCH_CAP_PER_INTEREST = 3


def _build_provider(platform: str) -> Any | None:
    """Instantiate the V3 provider class for ``platform``.

    Returns None if the platform name is unknown so the caller can skip it.
    """
    import httpx as _httpx

    load_dotenv()

    client = _httpx.Client(
        follow_redirects=True,
        timeout=_httpx.Timeout(20.0),
        headers={"User-Agent": "heatedtopics-v3/0.1 (+anonymous-public-data)"},
    )
    if platform.startswith("dailyhot:"):
        from heated_topics_v3.providers.dailyhot import DailyHotApiProvider

        route = platform.split(":", 1)[1]
        return DailyHotApiProvider(route, client=client), client
    if platform == "juejin":
        from heated_topics_v3.providers.juejin import JuejinProvider

        return JuejinProvider(client), client
    if platform == "toutiao":
        from heated_topics_v3.providers.toutiao import ToutiaoProvider

        return ToutiaoProvider(client), client
    if platform == "baidu_hot":
        from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

        return BaiduHotProvider(client), client
    if platform == "zhihu_hot":
        from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

        return ZhihuHotProvider(client, os.getenv("ZHIHU_COOKIE", "")), client
    if platform == "zhihu_daily":
        from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

        return ZhihuDailyProvider(client), client
    if platform == "sina_news":
        from heated_topics_v3.providers.sina_news import SinaNewsProvider

        return SinaNewsProvider(client), client
    if platform == "thepaper":
        from heated_topics_v3.providers.thepaper import ThePaperProvider

        return ThePaperProvider(client), client
    if platform == "netease_news":
        from heated_topics_v3.providers.netease_news import NeteaseNewsProvider

        return NeteaseNewsProvider(client), client
    try:
        client.close()
    except Exception:
        pass
    return None


# Alias raw provider metric names -> adapter keys (view/like/comment/favorite/share).
# Providers use varying names: juejin emits "views"/"likes"/"collects"/"comments",
# toutiao search uses "reads"/"comments", thepaper uses "praise_times", etc.
# Composite scores ("hot"/"hot_value"/"hot_score"/"engagement"/"search_rank") are
# platform ranking signals, NOT user engagement metrics — they pass through
# unmodified so to_discovered ignores them rather than mis-attributing as views.
_METRIC_ALIASES: dict[str, str] = {
    "view_count": "view",
    "views": "view",
    "reads": "view",
    "voteups": "like",
    "like_count": "like",
    "likes": "like",
    "praise_times": "like",
    "comment_count": "comment",
    "comments": "comment",
    "favorite_count": "favorite",
    "collects": "favorite",
    "share_count": "share",
    "shares": "share",
    # Pass-through (intentionally not aliased):
    #   hot / hot_value / hot_score / engagement / search_rank / interaction_num
}


def _normalize_heat_metrics(heat: Any) -> dict[str, Any]:
    """Build the heat dict consumed by ``candidate_adapter.to_discovered``.

    Real platform metrics (e.g. juejin ``views``) populate ``view/like/comment
    /favorite/share`` with provider-aliased names. Composite scores (heat.value,
    ``hot``/``hot_score``/etc.) are NOT mapped to ``view``: they're platform
    ranking signals, not engagement data. Without a real view metric, ``view``
    stays unset so downstream ``min_view_count`` filtering works honestly.
    """
    out: dict[str, Any] = {}
    for raw_k, v in (heat.metrics or {}).items():
        key = _METRIC_ALIASES.get(raw_k, raw_k)
        try:
            out.setdefault(key, int(v))
        except (TypeError, ValueError):
            continue
    return out


def _hotitem_to_article(
    item: HotItem, detail: ItemDetail | None, platform: str
) -> dict[str, Any] | None:
    """Convert a V3 HotItem (+ optional ItemDetail) into the dict shape
    that ``candidate_adapter.to_discovered`` expects.
    """
    if not item.item_id or not item.title or not item.url:
        return None
    body_text = ""
    if detail is not None and detail.content_status == "full_text" and detail.content:
        body_text = detail.content
    heat_dict = _normalize_heat_metrics(item.heat)
    heat_dict["rank"] = item.rank or 0
    return {
        "article_id": item.item_id,
        "title": item.title,
        "url": item.url,
        "source_url": item.url,
        "canonical_url": detail.source_url if detail is not None and detail.source_url != item.url else "",
        "body_text": body_text,
        "summary": item.summary or "",
        "author": str(
            item.raw_payload.get("author")
            or item.raw_payload.get("author_name")
            or item.raw_payload.get("author_handle")
            or item.raw_payload.get("account_name")
            or item.raw_payload.get("source_name")
            or ""
        ),
        "content_type": str(
            item.raw_payload.get("content_type")
            or ("article" if "zhuanlan.zhihu.com" in item.url else "question_answer" if "zhihu.com/question" in item.url else "")
        ),
        "published_at": item.publication_time or "",
        "tags": [],
        "heat": heat_dict,
        "platform": platform,
    }


def _call_provider_search(
    provider: Any, platform: str, keyword: str, page_size: int, collected_at: str
) -> Any:
    """Invoke a provider's ``search`` regardless of signature variant.

    The ``NewsProvider`` protocol declares
    ``search(keyword, page, page_size, collected_at)`` but two providers
    (toutiao, sina_news) shipped with a different shape before the
    protocol was finalized. Try the protocol first, fall back per-provider.
    """
    try:
        return provider.search(
            keyword,
            page=1,
            page_size=page_size,
            collected_at=collected_at,
        )
    except TypeError:
        pass
    if platform == "toutiao":
        return provider.search(keyword, collected_at)
    if platform == "sina_news":
        return provider.search(keyword, collected_at, page=1)
    # Last-ditch: try the (keyword, page) 2-arg variant.
    return provider.search(keyword, 1)


# --- v2.1.6: per-provider sync helpers for the parallel fetch path --------
# These are the building blocks for the async parallel pipeline
# (``_fetch_v3_candidates_async`` / ``_fetch_last30days_candidates_async``).
# Each helper is a pure sync function that owns its ``httpx.Client`` lifetime
# (closed in ``finally``) and is safe to invoke via ``asyncio.to_thread``.
# Keeping them sync (vs. rewriting providers as ``async def``) avoids touching
# the per-provider contract — providers are sync by design across the board.


def _fetch_provider_hot_list_sync(
    platform: str,
    collected_at: str,
    *,
    detail_cap: int | None = None,
    hot_cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch hot list + per-item detail for ONE platform (sync).

    Safe to call from ``asyncio.to_thread``. Returns a list of article dicts
    shaped like ``_hotitem_to_article`` output. Empty list on provider
    build failure, collect_hot_list crash, or no items.
    """
    built = _build_provider(platform)
    if built is None:
        logger.warning(
            "_fetch_provider_hot_list_sync: unknown platform '%s'", platform,
        )
        return []
    provider, client = built
    if detail_cap is None:
        detail_cap = _DETAIL_FETCH_CAP_BY_PLATFORM.get(platform, _DETAIL_FETCH_CAP)
    cache_path = None
    if hot_cache_dir is not None:
        cache_path = hot_cache_dir / collected_at[:10] / f"{platform}.json"
        try:
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    logger.info("hot cache hit: %s", cache_path)
                    return cached
        except (OSError, ValueError, TypeError):
            logger.warning("invalid hot cache, refetching: %s", cache_path)
    try:
        try:
            capture = provider.collect_hot_list(collected_at)
            items: tuple[HotItem, ...] = capture.items
        except Exception as exc:
            logger.warning(
                "provider %s.collect_hot_list failed: %s", platform, exc,
            )
            return []
        out: list[dict[str, Any]] = []
        cap_items = items[:detail_cap]
        for item in cap_items:
            try:
                detail = provider.fetch_detail(item, collected_at)
            except Exception as exc:
                logger.debug(
                    "provider %s.fetch_detail(%s) failed: %s",
                    platform, item.item_id, exc,
                )
                detail = None
            article = _hotitem_to_article(item, detail, platform)
            if article is not None:
                out.append(article)
        for item in items[detail_cap:]:
            article = _hotitem_to_article(item, None, platform)
            if article is not None:
                out.append(article)
        if cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as exc:
                logger.warning("failed to write hot cache %s: %s", cache_path, exc)
        return out
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _fetch_provider_search_sync(
    platform: str,
    track: str,
    collected_at: str,
    *,
    results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    detail_cap_per_interest: int = _SEARCH_DETAIL_FETCH_CAP_PER_INTEREST,
) -> list[dict[str, Any]]:
    """Run ONE search query on ONE platform (sync).

    Each (provider, track) pair becomes one ``asyncio.to_thread`` task —
    that is the unit of parallelism for the search pass (3 providers × 3
    tracks = up to 9 tasks instead of 9 sequential calls).
    """
    built = _build_provider(platform)
    if built is None:
        return []
    provider, client = built
    try:
        try:
            capture = _call_provider_search(
                provider, platform, track, results_per_interest, collected_at,
            )
            items = capture.items[:results_per_interest]
        except Exception as exc:
            logger.warning(
                "search %s(%s) failed: %s", platform, track, exc,
            )
            return []
        if not items:
            return []
        out: list[dict[str, Any]] = []
        cap_items = items[:detail_cap_per_interest]
        for item in cap_items:
            try:
                detail = provider.fetch_detail(item, collected_at)
            except Exception as exc:
                logger.debug(
                    "search %s.fetch_detail(%s) failed: %s",
                    platform, item.item_id, exc,
                )
                detail = None
            article = _hotitem_to_article(item, detail, platform)
            if article is not None:
                article["search_query"] = track
                out.append(article)
        for item in items[detail_cap_per_interest:]:
            article = _hotitem_to_article(item, None, platform)
            if article is not None:
                article["search_query"] = track
                out.append(article)
        return out
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _fetch_one_last30days_query_sync(
    spec: user_profile.UserSpec,
    cfg: dict[str, Any],
    query: str,
    base_save_dir: Path,
) -> tuple[str, list[dict[str, Any]]]:
    """Run ONE last30days CLI invocation for one query (sync).

    Returns ``(query, articles)`` so the orchestrator can log per-query
    yields. Failures yield ``(query, [])`` so ``asyncio.gather`` doesn't
    poison sibling tasks.
    """
    cli_path = Path(cfg["cli_path"])
    save_dir = base_save_dir / _safe_query_dirname(query)
    try:
        report_path = last30days_source.run(
            cli_path=cli_path,
            query=query,
            days=int(cfg.get("days", 30)),
            save_dir=save_dir,
            fetch_bodies=bool(cfg.get("fetch_bodies", True)),
            platforms=tuple(cfg.get("platforms") or ()),
            timeout=float(cfg.get("timeout", 120.0)),
        )
        report = last30days_source.parse_report(report_path)
    except Exception as exc:
        logger.warning(
            "user %s: last30days fetch for query %r failed: %s",
            spec.user_id, query, exc,
        )
        return (query, [])
    items, details = last30days_adapter.to_hot_items(report)
    articles: list[dict[str, Any]] = []
    for item, detail in zip(items, details):
        article = _hotitem_to_article(item, detail, item.platform)
        if article is None:
            continue
        article = body_enricher.enrich_article(article)
        article["search_query"] = query
        articles.append(article)
    return (query, articles)


def _is_hot_relevant(article: dict[str, Any], tracks: list[str]) -> bool:
    """Loose relevance: any track name appears in title/body/summary.

    Cheap stand-in for "does this hot-list item actually match what the
    user cares about". Embedding similarity would be more accurate but
    costs an extra LLM/embedding round-trip per hot item; the keyword
    check is a 0-cost filter that catches obvious mismatches like
    "解放军警告" vs tracks = ["非遗", "地方习俗"…].
    """
    if not tracks:
        return False
    title = article.get("title") or ""
    body_text = article.get("body_text") or ""
    summary = article.get("summary") or ""
    haystack = f"{title} {body_text} {summary}".lower()
    if not haystack.strip():
        return False
    return any(t.lower() in haystack for t in tracks if t.strip())


def _is_article_candidate(article: dict[str, Any]) -> bool:
    return _is_article_item_candidate(article)

def _is_article_item_candidate(article: dict[str, Any]) -> bool:
    """Filter item types, without excluding an entire platform."""
    platform = str(article.get("platform") or "").casefold()
    content_type = str(article.get("content_type") or "").casefold().strip()
    if content_type in _NON_ARTICLE_TYPES:
        return False
    if content_type in {"article", "column", "news", "longform", "图文"}:
        return True
    url = str(article.get("url") or "").casefold()
    title = str(article.get("title") or "").casefold()
    media_markers = ("/video", "/live", "b23.tv", "douyin.com/video", "vlog", "视频", "直播")
    if any(marker in url or marker in title for marker in media_markers):
        return False
    if platform in {"bilibili", "douyin"} and not article.get("body_text"):
        return False
    return True


def _sort_article_sources(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable article providers first, while preserving source-local order."""
    def priority(article: dict[str, Any]) -> tuple[int, int]:
        platform = str(article.get("platform") or "").casefold()
        if platform == "zhihu":
            content_type = str(article.get("content_type") or "").casefold()
            url = str(article.get("url") or "").casefold()
            # Prefer Zhihu column articles; question/answer items are the
            # explicit fallback because their body is answer-dependent.
            if "zhuanlan.zhihu.com" in url or content_type in {"article", "column"}:
                return (9, 0)
            return (11, 0)
        return (_ARTICLE_SOURCE_PRIORITY.get(platform, 50), 0)
    return [
        article for _, article in sorted(
            enumerate(articles),
            key=lambda pair: (*priority(pair[1]), pair[0]),
        )
    ]


def _rebalance_pool(
    hot: list[dict[str, Any]],
    search: list[dict[str, Any]],
    tracks: list[str],
    target_limit: int,
    prefer_search: bool,
) -> list[dict[str, Any]]:
    """Build the final candidate pool. Search is trusted over hot when
    prefer_search=True; hot-list items that don't mention any of the user's
    tracks are dropped so the engine's MMR doesn't get pulled back to
    generic-news top picks.
    """
    if not prefer_search:
        return hot + search
    relevant_hot = [a for a in hot if _is_hot_relevant(a, tracks)]
    other_hot = [a for a in hot if not _is_hot_relevant(a, tracks)]
    plenty = target_limit * 4  # search-only pool > 4× limit = drop hot
    enough = target_limit  # search >= limit: keep some relevant_hot for variety
    target_pool_size = max(40, target_limit * 4)
    if len(search) >= plenty:
        return list(search)[:target_pool_size]
    pool: list[dict[str, Any]] = list(search)
    if len(search) >= enough:
        pool.extend(relevant_hot[:target_limit])
    else:
        pool.extend(relevant_hot)
        if len(pool) < target_pool_size:
            pool.extend(other_hot[: target_pool_size - len(pool)])
    return pool[:target_pool_size]


def _spec_tracks(spec: user_profile.UserSpec) -> list[str]:
    """Return non-empty track_1/track_2 as a list (search keywords)."""
    return [t for t in (spec.track_1, spec.track_2) if t and t.strip()]


def fetch_candidates(
    spec: user_profile.UserSpec,
    *,
    providers: list[str] | None = None,
    data_dir: Path | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    target_limit: int = 15,
    keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch hot articles for one user from V3 providers.

    Two passes:
      1. Hot list (every enabled provider). Provides topical breadth.
      2. Search (top-K interests × search-capable providers). Provides
         topic-aligned candidates that are *not* on today's hot board.

    When ``prefer_search=True`` (default) the pool is built from search
    first; hot-list items that don't mention any of the user's interests
    are dropped unless we need them to backfill. URL dedup applies across
    both passes. Search results carry an extra ``search_query`` field.

    Failures in individual providers or individual searches are isolated:
    one bad pair returns zero items rather than crashing the whole fetch.
    """
    enabled = list(providers) if providers else list(_DEFAULT_PROVIDERS)
    collected_at = datetime.now(SHANGHAI).isoformat()
    seen_urls: set[str] = set()
    hot_articles: list[dict[str, Any]] = []
    search_articles: list[dict[str, Any]] = []

    def _add_to(bucket: list[dict[str, Any]], article: dict[str, Any] | None) -> None:
        if article is None:
            return
        url = article.get("url") or ""
        if url and url in seen_urls:
            return
        if url:
            seen_urls.add(url)
        bucket.append(article)

    # --- Pass 1: hot list --------------------------------------------------
    for platform in enabled:
        built = _build_provider(platform)
        if built is None:
            logger.warning("fetch_candidates: unknown platform '%s'", platform)
            continue
        provider, client = built
        try:
            try:
                capture = provider.collect_hot_list(collected_at)
                items: tuple[HotItem, ...] = capture.items
            except Exception as exc:
                logger.warning("provider %s.collect_hot_list failed: %s", platform, exc)
                continue
            cap_items = items[:_DETAIL_FETCH_CAP_BY_PLATFORM.get(
                platform, _DETAIL_FETCH_CAP)]
            for item in cap_items:
                try:
                    detail = provider.fetch_detail(item, collected_at)
                except Exception as exc:
                    logger.debug(
                        "provider %s.fetch_detail(%s) failed: %s",
                        platform,
                        item.item_id,
                        exc,
                    )
                    detail = None
                _add_to(hot_articles, _hotitem_to_article(item, detail, platform))
            for item in items[_DETAIL_FETCH_CAP:]:
                _add_to(
                    hot_articles, _hotitem_to_article(item, None, platform)
                )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    # --- Pass 2: search ---------------------------------------------------
    # LLM-extracted keywords (if provided) take precedence over the raw
    # track_1/track_2 — they are typically more specific and trending.
    if keywords:
        tracks = [k for k in keywords if k and k.strip()]
    else:
        tracks = _spec_tracks(spec)
    # Hot list is the primary source. Search is only a backfill when the
    # relevant hot-list pool is smaller than the requested recommendation
    # count; this prevents search results from replacing today's hot topics.
    relevant_hot_count = sum(
        1 for article in hot_articles if _is_hot_relevant(article, tracks)
    )
    if use_search and tracks and relevant_hot_count < target_limit:
        search_enabled = [
            p
            for p in (
                list(search_providers)
                if search_providers
                else list(_SEARCH_PROVIDERS)
            )
            if p in enabled
        ]
        if search_enabled:
            top_tracks = tracks[:search_top_k]
            logger.info(
                "search pass: providers=%s tracks=%s",
                search_enabled,
                top_tracks,
            )
            for platform in search_enabled:
                built = _build_provider(platform)
                if built is None:
                    continue
                provider, client = built
                try:
                    for track in top_tracks:
                        try:
                            capture = _call_provider_search(
                                provider,
                                platform,
                                track,
                                search_results_per_interest,
                                collected_at,
                            )
                            items = capture.items[:search_results_per_interest]
                        except Exception as exc:
                            logger.warning(
                                "search %s(%s) failed: %s",
                                platform,
                                track,
                                exc,
                            )
                            continue
                        if not items:
                            continue
                        cap_items = items[:_SEARCH_DETAIL_FETCH_CAP_PER_INTEREST]
                        for item in cap_items:
                            try:
                                detail = provider.fetch_detail(item, collected_at)
                            except Exception as exc:
                                logger.debug(
                                    "search %s.fetch_detail(%s) failed: %s",
                                    platform,
                                    item.item_id,
                                    exc,
                                )
                                detail = None
                            article = _hotitem_to_article(item, detail, platform)
                            if article is not None:
                                article["search_query"] = track
                            _add_to(search_articles, article)
                        for item in items[_SEARCH_DETAIL_FETCH_CAP_PER_INTEREST:]:
                            article = _hotitem_to_article(item, None, platform)
                            if article is not None:
                                article["search_query"] = track
                            _add_to(search_articles, article)
                finally:
                    close = getattr(client, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass

    if use_search:
        return _rebalance_pool(
            hot_articles,
            search_articles,
            tracks,
            target_limit=target_limit,
            prefer_search=False,
        )
    return hot_articles


# --- last30days source support ----------------------------------------------


def _first_track(spec: user_profile.UserSpec) -> str:
    """Return the first non-empty track name, or '' if none."""
    return (spec.track_1 or spec.track_2 or "").strip()


def _safe_query_dirname(query: str) -> str:
    """Filesystem-safe slug for a query string (sub-dir per query)."""
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", query).strip("_")
    return safe or "q"


def _resolve_last30days_queries(
    cfg: dict[str, Any],
    *,
    keywords: list[str] | None,
    spec: user_profile.UserSpec,
    max_queries: int,
) -> list[str]:
    """Resolve the list of last30days queries for one user.

    Resolution order (highest priority first):
    1. ``cfg['queries']`` — explicit list of queries in caller config.
    2. ``cfg['query']`` — legacy single query in caller config.
    3. ``keywords[:max_queries]`` — LLM-extracted keywords (3 by default).
    4. ``[spec.track_1, spec.track_2]`` — fallback to raw tracks.

    Returns an empty list if no resolvable queries remain.
    """
    if cfg.get("queries"):
        return [q for q in cfg["queries"] if q and q.strip()][:max_queries]
    if cfg.get("query"):
        return [cfg["query"]]
    if keywords:
        return [k for k in keywords if k and k.strip()][:max_queries]
    tracks = _spec_tracks(spec)
    return tracks[:max_queries] if tracks else []


def _fetch_last30days_candidates(
    spec: user_profile.UserSpec,
    cfg: dict[str, Any],
    *,
    keywords: list[str] | None = None,
    max_queries: int = 3,
) -> list[dict[str, Any]]:
    """Invoke last30days CLI for one user; return V3 article dicts.

    Pipeline: per-query subprocess → parse JSON → adapter (Item →
    HotItem/ItemDetail) → ``_hotitem_to_article``. The returned list is
    in the same shape as ``fetch_candidates``, so downstream code needs
    no awareness of which source produced each article.

    Multi-query mode (v2.1.5): runs the CLI for the first resolved
    query. If the cumulative unique-article count is at or below
    ``cfg['low_water_mark']`` (default 3), the next resolved query is
    tried as well; this escalates up to ``max_queries`` total. Stop
    early as soon as the threshold is exceeded — niche personas that
    produce a thin result from one angle still get coverage, but
    mainstream personas don't pay for redundant subprocesses.

    Each query gets its own sub-dir under ``<save_dir>/<user_id>/`` so
    per-query ``report.json`` files don't clobber each other. URL dedup
    spans queries so a popular URL appearing under multiple angles is
    only kept once (first-seen wins).

    Query resolution: see ``_resolve_last30days_queries``.
    """
    cli_path = Path(cfg["cli_path"])
    queries = _resolve_last30days_queries(
        cfg, keywords=keywords, spec=spec, max_queries=max_queries,
    )
    if not queries:
        logger.warning("user %s: no query for last30days, skipping", spec.user_id)
        return []

    low_water_mark = max(1, int(cfg.get("low_water_mark", 3)))

    base_save_dir = Path(cfg.get("save_dir", "data/last30days")) / spec.user_id
    seen_urls: set[str] = set()
    articles: list[dict[str, Any]] = []
    queries_used: list[str] = []

    for q in queries:
        save_dir = base_save_dir / _safe_query_dirname(q)
        try:
            report_path = last30days_source.run(
                cli_path=cli_path,
                query=q,
                days=int(cfg.get("days", 30)),
                save_dir=save_dir,
                fetch_bodies=bool(cfg.get("fetch_bodies", True)),
                platforms=tuple(cfg.get("platforms") or ()),
                timeout=float(cfg.get("timeout", 120.0)),
            )
            report = last30days_source.parse_report(report_path)
        except Exception as exc:
            logger.warning(
                "user %s: last30days fetch for query %r failed: %s",
                spec.user_id, q, exc,
            )
            # Treat a failed query as if it returned 0 — keeps the
            # escalation logic well-defined (we may still try the next).
            queries_used.append(q)
            continue

        items, details = last30days_adapter.to_hot_items(report)
        n_before = len(articles)
        for item, detail in zip(items, details):
            article = _hotitem_to_article(item, detail, item.platform)
            if article is None:
                continue
            article = body_enricher.enrich_article(article)
            url = article.get("url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            article["search_query"] = q
            articles.append(article)
        queries_used.append(q)
        logger.info(
            "user %s: last30days query=%r kept %d/%d items (cumulative=%d)",
            spec.user_id, q, len(articles) - n_before, len(items), len(articles),
        )

        # Adaptive escalation: stop as soon as we exceed the low-water
        # mark. Otherwise loop continues to the next query.
        if len(articles) > low_water_mark:
            break

    if len(queries_used) < len(queries):
        logger.info(
            "user %s: last30days low-water reached after %d query(ies) "
            "(%d articles > threshold=%d); skipping remaining %d query(ies)",
            spec.user_id, len(queries_used), len(articles), low_water_mark,
            len(queries) - len(queries_used),
        )
    return articles


def _fetch_candidates_for_user(
    spec: user_profile.UserSpec,
    *,
    source: str,
    last30days_config: dict[str, Any] | None,
    target_limit: int = 15,
    v3_providers: list[str] | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    keywords: list[str] | None = None,
    last30days_max_queries: int = 3,
) -> list[dict[str, Any]]:
    """Dispatch candidate fetching based on ``source``.

    - ``v3-hotlist``: only V3 providers (default; preserves existing behaviour).
    - ``last30days``: only last30days CLI (requires ``last30days_config``).
    - ``both``: V3 first, last30days second with URL dedup (V3 wins ties).

    ``keywords`` (LLM-extracted) override track_1/track_2 for both V3 search
    queries and the last30days query list (top ``last30days_max_queries``
    keywords feed the CLI — each one becomes a separate query that gets its
    own subprocess + report).
    """
    articles: list[dict[str, Any]] = []
    if source in ("v3-hotlist", "both"):
        articles.extend(
            fetch_candidates(
                spec,
                providers=v3_providers,
                use_search=use_search,
                prefer_search=prefer_search,
                search_providers=search_providers,
                search_top_k=search_top_k,
                search_results_per_interest=search_results_per_interest,
                target_limit=target_limit,
                keywords=keywords,
            )
        )
    if source in ("last30days", "both"):
        if last30days_config is None:
            if source == "last30days":
                logger.warning(
                    "user %s: source=last30days but no config; returning []",
                    spec.user_id,
                )
                return []
        else:
            l30 = _fetch_last30days_candidates(
                spec, last30days_config,
                keywords=keywords, max_queries=last30days_max_queries,
            )
            if source == "both":
                seen = {a.get("url") for a in articles if a.get("url")}
                for a in l30:
                    if a.get("url") and a["url"] in seen:
                        continue
                    if a.get("url"):
                        seen.add(a["url"])
                    articles.append(a)
            else:
                articles.extend(l30)
    return articles


# --- v2.1.6: async parallel fetch pipeline ---------------------------------
# Replaces the synchronous ``fetch_candidates`` / ``_fetch_last30days_candidates``
# / ``_fetch_candidates_for_user`` calls inside ``_run_one_user_async``.
# Each provider / search pair / last30days query runs as its own
# ``asyncio.to_thread`` task and is gathered with ``asyncio.gather`` —
# wall-clock time drops from sum(providers) to max(providers), and from
# sum(queries) to max(queries). The legacy low_water_mark early-exit on
# last30days is removed because parallelism and early-exit are mutually
# exclusive (skipping subsequent queries defeats the purpose of running
# them concurrently). URL dedup is preserved across sources.


async def _fetch_v3_candidates_async(
    spec: user_profile.UserSpec,
    *,
    providers: list[str] | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    target_limit: int = 15,
    keywords: list[str] | None = None,
    hot_cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Parallel async version of ``fetch_candidates``.

    Same return shape as the sync version. Pass 1 (hot list) and Pass 2
    (search) both gather ``asyncio.to_thread`` tasks — providers run in
    their own threads so their blocking ``httpx`` I/O doesn't stall the
    event loop or each other. URL dedup and rebalance rules are identical.
    """
    enabled = list(providers) if providers else list(_DEFAULT_PROVIDERS)
    collected_at = datetime.now(SHANGHAI).isoformat()
    seen_urls: set[str] = set()
    hot_articles: list[dict[str, Any]] = []
    search_articles: list[dict[str, Any]] = []

    def _add_to(bucket: list[dict[str, Any]], article: dict[str, Any] | None) -> None:
        if article is None:
            return
        url = article.get("url") or ""
        if url and url in seen_urls:
            return
        if url:
            seen_urls.add(url)
        bucket.append(article)

    # Pass 1: hot list — one to_thread task per provider.
    results = await asyncio.gather(
        *[
            asyncio.to_thread(
                _fetch_provider_hot_list_sync, p, collected_at,
                hot_cache_dir=hot_cache_dir,
            )
            for p in enabled
        ],
        return_exceptions=True,
    )
    for platform, result in zip(enabled, results):
        if isinstance(result, BaseException):
            logger.warning(
                "user %s: provider %s raised in parallel hot-list: %s",
                spec.user_id, platform, result,
            )
            continue
        for article in result:
            _add_to(hot_articles, article)

    tracks = [k for k in (keywords or []) if k and k.strip()]
    if not tracks:
        tracks = _spec_tracks(spec)
    relevant_hot_count = sum(
        1 for article in hot_articles if _is_hot_relevant(article, tracks)
    )
    if use_search and tracks and relevant_hot_count < target_limit:
        if tracks:
            search_enabled = [
                p
                for p in (
                    list(search_providers)
                    if search_providers
                    else list(_SEARCH_PROVIDERS)
                )
                if p in enabled
            ]
            if search_enabled:
                top_tracks = tracks[:search_top_k]
                keys = [
                    (p, t)
                    for p in search_enabled
                    for t in top_tracks
                ]
                tasks = [
                    asyncio.to_thread(
                        _fetch_provider_search_sync,
                        p, t, collected_at,
                        results_per_interest=search_results_per_interest,
                    )
                    for p, t in keys
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for (platform, track), result in zip(keys, results):
                    if isinstance(result, BaseException):
                        logger.warning(
                            "user %s: search %s(%s) raised in parallel: %s",
                            spec.user_id, platform, track, result,
                        )
                        continue
                    for article in result:
                        _add_to(search_articles, article)

    if use_search:
        return _rebalance_pool(
            hot_articles,
            search_articles,
            tracks,
            target_limit=target_limit,
            prefer_search=False,
        )
    return hot_articles


async def _fetch_last30days_candidates_async(
    spec: user_profile.UserSpec,
    cfg: dict[str, Any],
    *,
    keywords: list[str] | None = None,
    max_queries: int = 3,
) -> list[dict[str, Any]]:
    """Parallel async version: every resolved query runs concurrently.

    Drops the legacy ``low_water_mark`` early-exit (mutually exclusive with
    parallelism). URL dedup across queries is preserved (first-seen wins).
    Per-query failures are logged and skipped — sibling queries are unaffected.
    """
    queries = _resolve_last30days_queries(
        cfg, keywords=keywords, spec=spec, max_queries=max_queries,
    )
    if not queries:
        logger.warning(
            "user %s: no query for last30days, skipping", spec.user_id,
        )
        return []
    base_save_dir = Path(cfg.get("save_dir", "data/last30days")) / spec.user_id
    pairs = await asyncio.gather(
        *[
            asyncio.to_thread(
                _fetch_one_last30days_query_sync,
                spec, cfg, q, base_save_dir,
            )
            for q in queries
        ],
        return_exceptions=True,
    )
    seen_urls: set[str] = set()
    articles: list[dict[str, Any]] = []
    for query, result in zip(queries, pairs):
        if isinstance(result, BaseException):
            logger.warning(
                "user %s: last30days query %r failed: %s",
                spec.user_id, query, result,
            )
            continue
        q, q_articles = result
        n_before = len(articles)
        for article in q_articles:
            url = article.get("url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            articles.append(article)
        logger.info(
            "user %s: last30days query=%r kept %d/%d items (cumulative=%d)",
            spec.user_id, q, len(articles) - n_before, len(q_articles),
            len(articles),
        )
    return articles


async def _fetch_candidates_for_user_async(
    spec: user_profile.UserSpec,
    *,
    source: str,
    last30days_config: dict[str, Any] | None,
    target_limit: int = 15,
    v3_providers: list[str] | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    keywords: list[str] | None = None,
    last30days_max_queries: int = 3,
    hot_cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Parallel async dispatch: V3 and last30days both run concurrently.

    Equivalent to ``_fetch_candidates_for_user`` (sync) but each source is
    a single ``await``. Used by ``_run_one_user_async`` instead of the sync
    function so the event loop can multiplex LLM / embedding / fetch I/O.
    """
    if source not in ("v3-hotlist", "last30days", "both"):
        raise ValueError(f"unknown source={source!r}")

    tasks: list[Awaitable[list[dict[str, Any]]]] = []
    keys: list[str] = []
    if source in ("v3-hotlist", "both"):
        tasks.append(
            _fetch_v3_candidates_async(
                spec,
                providers=v3_providers,
                use_search=use_search,
                prefer_search=prefer_search,
                search_providers=search_providers,
                search_top_k=search_top_k,
                search_results_per_interest=search_results_per_interest,
                target_limit=target_limit,
                keywords=keywords,
                hot_cache_dir=hot_cache_dir,
            )
        )
        keys.append("v3")
    if source in ("last30days", "both"):
        if last30days_config is None:
            if source == "last30days":
                logger.warning(
                    "user %s: source=last30days but no config; returning []",
                    spec.user_id,
                )
                return []
        else:
            tasks.append(
                _fetch_last30days_candidates_async(
                    spec, last30days_config,
                    keywords=keywords, max_queries=last30days_max_queries,
                )
            )
            keys.append("l30")

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[dict[str, Any]] = []
    for key, result in zip(keys, results):
        if isinstance(result, BaseException):
            logger.warning(
                "user %s: %s fetch raised: %s", spec.user_id, key, result,
            )
            continue
        articles.extend(result)
    return articles


def _build_shared_runtime(
    shared_data_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Construct shared LLM and embedding services once per process."""
    from openbiliclaw.config import Config, LLMProviderConfig
    from openbiliclaw.llm.registry import build_embedding_service, build_llm_registry
    from openbiliclaw.llm.service import LLMService
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.storage.database import Database

    base_dir = shared_data_dir or Path.cwd() / ".openbiliclaw_shared"
    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "shared.db"
    database = Database(db_path)
    database.initialize()
    memory_manager = MemoryManager(base_dir, database=database)

    config = None
    if config_path is not None:
        config = runtime.load_openbiliclaw_config(config_path)
    if config is None:
        config = Config()
        config.llm.default_provider = "openai_compatible"
        config.llm.openai_compatible = LLMProviderConfig(
            api_key=os.environ.get("OPENBILICLAW_LLM_API_KEY", ""),
            model="MiniMax-M2.7",
            base_url="https://api.minimaxi.com/v1",
        )
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"
        runtime.configure_model_env(config)
    elif not config.llm.embedding.provider.strip():
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"
        runtime.configure_model_env(config)

    registry = build_llm_registry(config)
    llm_service = LLMService(registry=registry, memory=memory_manager)
    embedding_service = build_embedding_service(config, registry)

    return {
        "llm": llm_service,
        "embedding": embedding_service,
        "_memory_manager": memory_manager,
        "_database": database,
    }


def build_recommender(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    shared_runtime: Any | None = None,
    persist: bool = False,
) -> Any:
    """Build a per-user RecommendationEngine pointing at data_dir.

    LLM service and embedding service are shared across users
    (shared_runtime). Database, MemoryManager, and RecommendationEngine
    are per-user.
    """
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.recommendation.engine import RecommendationEngine
    from openbiliclaw.storage.database import Database

    if shared_runtime is None:
        shared_runtime = _build_shared_runtime(shared_data_dir=data_dir.parent)

    user_db_path = data_dir / "openbiliclaw.db"
    user_db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(user_db_path)
    database.initialize()

    memory_manager = MemoryManager(data_dir, database=database)

    engine = RecommendationEngine(
        llm=shared_runtime["llm"],
        database=database,
        embedding_service=shared_runtime.get("embedding"),
    )
    # Stash per-user handles so callers can close them.
    engine._ht_memory_manager = memory_manager  # type: ignore[attr-defined]
    engine._ht_database = database  # type: ignore[attr-defined]
    return engine


async def _run_one_user_async(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int,
    body_max_chars: int,
    per_user_timeout: float,
    providers: list[str] | None,
    shared_runtime: Any | None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    source: str = "v3-hotlist",
    last30days_config: dict[str, Any] | None = None,
    last30days_max_queries: int = 3,
    use_keyword_extraction: bool = True,
    keyword_cache_dir: Path | None = None,
    user_cache_root: Path | None = None,
    hard_cache_dir: Path | None = None,
    hot_cache_dir: Path | None = None,
    min_view_count: int = 0,
    heat_source: str = "rank",
    use_llm_refilter: bool = False,
    refilter_batch_size: int = 10,
) -> dict[str, Any]:
    """Async body of run_one_user.

    New v2.1.4 knobs (all default off / v2.1.2 behavior):
    - ``min_view_count``: hard-drop candidates with view_count below this.
    - ``heat_source``: ``"rank"`` (1/rank, default) or ``"view"``
      (log-scaled real engagement; falls back to rank when view_count=0).
    - ``use_llm_refilter``: after the embedding pre-filter, ask the LLM
      to drop candidates that look keyword-relevant but are actually
      off-persona.

    v2.1.5 knob:
    - ``last30days_max_queries``: cap on how many of the LLM-extracted
      keywords become separate last30days CLI queries (default 3, set
      to 1 to restore the legacy single-query behaviour). Resolution
      is centralised in ``_resolve_last30days_queries``; caller-supplied
      ``last30days_config['queries']`` always wins.
    """
    # 1) Extract (or load cached) hot keywords from the user's profile.
    keywords: list[str] | None = None
    if use_keyword_extraction and shared_runtime is not None:
        cache_dir = keyword_cache_dir or (data_dir / "_keyword_cache")
        try:
            keywords = await extract_or_load(
                spec, shared_runtime["llm"], cache_dir,
            )
        except Exception as exc:
            logger.warning(
                "keyword extraction crashed for %s, falling back to tracks: %s",
                spec.user_id, exc,
            )
            keywords = None

    # 1.5) Embed the 3 keywords once per user (EmbeddingService caches via
    # L1+L2, so repeat runs within a session / across sessions are free).
    keyword_vectors: list[list[float]] = []
    if keywords and shared_runtime is not None:
        from heated_topics_v3.openbiliclaw_integration import relevance
        embedding_service = shared_runtime.get("embedding")
        if embedding_service is not None:
            keyword_vectors = await relevance.embed_keywords(
                keywords, embedding_service,
            )
            if not keyword_vectors:
                logger.warning(
                    "all keyword embeddings failed for %s; "
                    "falling back to 1/rank scoring",
                    spec.user_id,
                )

    # 2) Fetch candidates using keywords (or track fallback).
    # v2.1.6: async parallel path — providers / last30days queries run
    # concurrently inside the orchestrator (vs. the legacy sequential
    # ``_fetch_candidates_for_user``). See ``_fetch_candidates_for_user_async``.
    articles = await _fetch_candidates_for_user_async(
        spec,
        source=source,
        last30days_config=last30days_config,
        last30days_max_queries=last30days_max_queries,
        target_limit=limit,
        v3_providers=providers,
        use_search=use_search,
        prefer_search=prefer_search,
        search_providers=search_providers,
        search_top_k=search_top_k,
        search_results_per_interest=search_results_per_interest,
        keywords=keywords,
        hot_cache_dir=hot_cache_dir or data_dir.parent / "hot_cache",
    )
    if not articles:
        return _user_failure(
            user_id=spec.user_id,
            error_code="no_candidates",
            error_detail=f"Fetched 0 articles from providers={providers or 'all'}",
        )
    # Some providers return only a card excerpt even after their detail call.
    # Give every short candidate one final platform-page enrichment attempt
    # before embeddings/filtering; long bodies are left untouched.
    enriched = await asyncio.gather(
        *[asyncio.to_thread(body_enricher.enrich_article, article) for article in articles],
        return_exceptions=True,
    )
    articles = [
        result if isinstance(result, dict) else article
        for article, result in zip(articles, enriched)
    ]
    searched_articles = list(articles)
    before_article_filter = len(articles)
    articles = _sort_article_sources(
        [article for article in articles if _is_article_item_candidate(article)]
    )
    logger.info(
        "user %s: article-only source filter kept %d/%d candidates",
        spec.user_id, len(articles), before_article_filter,
    )
    if not articles:
        return _user_failure(
            user_id=spec.user_id,
            error_code="no_article_candidates",
            error_detail="Fetched candidates, but none came from article sources",
        )
    embedding_service = (
        shared_runtime.get("embedding") if shared_runtime else None
    )
    candidates = await candidate_adapter.to_discovered(
        articles,
        platform=articles[0].get("platform", "juejin")
        if isinstance(articles[0], dict) and "platform" in articles[0]
        else "juejin",
        embedding_service=embedding_service,
        keyword_vectors=keyword_vectors,
        sim_threshold=0.5,
        min_view_count=min_view_count,
        heat_source=heat_source,
    )
    # If articles don't carry 'platform' per-item, attribute by provider list order.
    if not any(isinstance(a, dict) and "platform" in a for a in articles):
        if providers and len(providers) == 1:
            candidates = await candidate_adapter.to_discovered(
                articles, platform=providers[0],
                embedding_service=embedding_service,
                keyword_vectors=keyword_vectors,
                sim_threshold=0.5,
                min_view_count=min_view_count,
                heat_source=heat_source,
            )

    # Niche fallback is lexical-only: never turn an empty semantic match into
    # an arbitrary hot-list recommendation. This keeps recall for embedding
    # edge cases while preventing unrelated trending content from leaking in.
    if use_search and keyword_vectors and not candidates:
        fallback_tracks = keywords or _spec_tracks(spec)
        fallback_articles = [
            article for article in articles
            if _is_hot_relevant(article, fallback_tracks)
        ]
        if not fallback_articles:
            return _user_failure(
                user_id=spec.user_id,
                error_code="no_relevant_candidates",
                error_detail=(
                    f"Fetched {len(articles)} articles but none matched "
                    "the user interests"
                ),
            )
        logger.info(
            "user %s: strict sim pre-filter dropped all %d articles; "
            "retrying with %d lexical matches",
            spec.user_id, len(articles), len(fallback_articles),
        )
        niche_platform = (
            articles[0].get("platform", "juejin")
            if isinstance(articles[0], dict) and "platform" in articles[0]
            else "juejin"
        )
        candidates = await candidate_adapter.to_discovered(
            fallback_articles,
            platform=niche_platform,
            embedding_service=embedding_service,
            keyword_vectors=keyword_vectors,
            sim_threshold=0.0,
            min_view_count=0,
            heat_source=heat_source,
        )
        if not any(isinstance(a, dict) and "platform" in a for a in articles):
            if providers and len(providers) == 1:
                candidates = await candidate_adapter.to_discovered(
                    fallback_articles, platform=providers[0],
                    embedding_service=embedding_service,
                    keyword_vectors=keyword_vectors,
                    sim_threshold=0.0,
                    min_view_count=0,
                    heat_source=heat_source,
                )

    # Optional LLM secondary filter: drop candidates that look
    # keyword-relevant but are actually off-persona. Off by default.
    if use_llm_refilter and shared_runtime is not None and candidates:
        from heated_topics_v3.openbiliclaw_integration import llm_refilter

        llm_service = shared_runtime.get("llm")
        if llm_service is None:
            logger.warning(
                "user %s: --llm-refilter requested but no LLM service; "
                "skipping",
                spec.user_id,
            )
        else:
            user_context = {
                "track_1": spec.track_1 or "",
                "track_2": spec.track_2 or "",
                "persona": spec.persona or "",
            }
            try:
                candidates = await llm_refilter.refilter_candidates(
                    candidates,
                    user_context=user_context,
                    llm_service=llm_service,
                    batch_size=refilter_batch_size,
                )
            except Exception as exc:
                logger.warning(
                    "user %s: LLM refilter crashed (%s); "
                    "keeping pre-filter candidates",
                    spec.user_id, exc,
                )
    profile = user_profile.build_onion_profile(spec)
    user_data_dir = user_profile.user_data_dir(data_dir, spec.user_id)
    engine = build_recommender(
        spec,
        data_dir=user_data_dir,
        shared_runtime=shared_runtime,
        persist=True,
    )
    try:
        async with asyncio.timeout(per_user_timeout):
            recommendations = await engine.serve_external_candidates(
                profile, candidates, limit=limit, persist=False,
                expression_mode="precomputed",
            )
    except TimeoutError:
        return _user_failure(
            user_id=spec.user_id,
            error_code="timeout",
            error_detail=f"exceeded {per_user_timeout}s",
        )
    except Exception as exc:
        logger.exception("user %s: engine failed", spec.user_id)
        return _user_failure(
            user_id=spec.user_id,
            error_code="engine_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    if not recommendations:
        return _user_failure(
            user_id=spec.user_id,
            error_code="no_recommendations",
            error_detail="Engine returned 0 recommendations",
        )

    # Build the query groups for one user-level content brief.
    from heated_topics_v3.openbiliclaw_integration import per_query_summary

    search_query_map: dict[str, str] = {}
    for art in articles:
        if isinstance(art, dict) and art.get("article_id"):
            sq = art.get("search_query") or ""
            if sq:
                search_query_map[str(art["article_id"])] = sq

    summary = ""
    if search_query_map and shared_runtime is not None:
        llm_service = shared_runtime.get("llm")
        if llm_service is not None:
            user_context = {
                "track_1": spec.track_1 or "",
                "track_2": spec.track_2 or "",
                "persona": spec.persona or "",
            }
            groups: dict[str, list[Any]] = {}
            for rec in recommendations:
                q = search_query_map.get(rec.content.content_id, "")
                if q:
                    groups.setdefault(q, []).append(rec)
            if groups:
                try:
                    summary = await per_query_summary.summarize_overall(
                        query_groups=list(groups.items()),
                        user_context=user_context,
                        llm_service=llm_service,
                    )
                except Exception as exc:
                    logger.warning(
                        "user %s: overall summary failed (%s); using empty summary",
                        spec.user_id, exc,
                    )

    return _user_payload(
        user_id=spec.user_id,
        track_1=spec.track_1,
        track_2=spec.track_2,
        persona=spec.persona,
        recommendations=recommendations,
        searched_articles=searched_articles,
        body_max_chars=body_max_chars,
        search_query_map=search_query_map,
        summary=summary,
    )


def run_one_user(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int = 15,
    body_max_chars: int = 50_000,
    per_user_timeout: float = 180.0,
    providers: list[str] | None = None,
    shared_runtime: Any | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    source: str = "v3-hotlist",
    last30days_config: dict[str, Any] | None = None,
    last30days_max_queries: int = 3,
    use_keyword_extraction: bool = True,
    keyword_cache_dir: Path | None = None,
    user_cache_root: Path | None = None,
    hard_cache_dir: Path | None = None,
    hot_cache_dir: Path | None = None,
    min_view_count: int = 0,
    heat_source: str = "rank",
    use_llm_refilter: bool = False,
    refilter_batch_size: int = 10,
) -> dict[str, Any]:
    """Synchronous wrapper around _run_one_user_async."""
    if use_keyword_extraction and shared_runtime is None:
        shared_runtime = _build_shared_runtime(
            shared_data_dir=data_dir.parent,
        )
    return asyncio.run(
        _run_one_user_async(
            spec,
            data_dir=(user_cache_root / spec.user_id / "hard_cache") if user_cache_root else (hard_cache_dir or data_dir),
            limit=limit,
            body_max_chars=body_max_chars,
            per_user_timeout=per_user_timeout,
            providers=providers,
            shared_runtime=shared_runtime,
            use_search=use_search,
            prefer_search=prefer_search,
            search_providers=search_providers,
            search_top_k=search_top_k,
            search_results_per_interest=search_results_per_interest,
            source=source,
            last30days_config=last30days_config,
            last30days_max_queries=last30days_max_queries,
            use_keyword_extraction=use_keyword_extraction,
            keyword_cache_dir=(user_cache_root / spec.user_id / "keyword_cache") if user_cache_root else keyword_cache_dir,
            hard_cache_dir=hard_cache_dir,
            hot_cache_dir=hot_cache_dir,
            min_view_count=min_view_count,
            heat_source=heat_source,
            use_llm_refilter=use_llm_refilter,
            refilter_batch_size=refilter_batch_size,
        )
    )


async def run_all_users(
    *,
    specs: list[user_profile.UserSpec],
    data_dir: Path,
    max_parallel: int = 3,
    limit: int = 15,
    body_max_chars: int = 50_000,
    per_user_timeout: float = 180.0,
    providers: list[str] | None = None,
    shared_runtime: Any | None = None,
    config_path: Path | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
    source: str = "v3-hotlist",
    last30days_config: dict[str, Any] | None = None,
    last30days_max_queries: int = 3,
    use_keyword_extraction: bool = True,
    keyword_cache_dir: Path | None = None,
    user_cache_root: Path | None = None,
    user_round_dirs: dict[str, Path] | None = None,
    hot_cache_dir: Path | None = None,
    min_view_count: int = 0,
    heat_source: str = "rank",
    use_llm_refilter: bool = False,
    refilter_batch_size: int = 10,
) -> dict[str, dict[str, Any]]:
    """Run recommendation for all users. Returns {user_id: payload}.

    v2: takes pre-loaded specs (caller loads from xlsx via excel_loader).
    Returns dict keyed by user_id so CLI can write per-user files without
    re-correlating with the input list.
    """
    if shared_runtime is None and (
        config_path is not None or use_keyword_extraction
    ):
        shared_runtime = _build_shared_runtime(
            shared_data_dir=data_dir,
            config_path=config_path,
        )
    sem = asyncio.Semaphore(min(max(1, max_parallel), 3))

    async def _one(spec: user_profile.UserSpec) -> dict[str, Any]:
        async with sem:
            try:
                user_root = user_cache_root / spec.user_id if user_cache_root else None
                return await _run_one_user_async(
                    spec,
                    data_dir=(user_root / "hard_cache") if user_root else data_dir,
                    limit=limit,
                    body_max_chars=body_max_chars,
                    per_user_timeout=per_user_timeout,
                    providers=providers,
                    shared_runtime=shared_runtime,
                    use_search=use_search,
                    prefer_search=prefer_search,
                    search_providers=search_providers,
                    search_top_k=search_top_k,
                    search_results_per_interest=search_results_per_interest,
                    source=source,
                    last30days_config=last30days_config,
                    last30days_max_queries=last30days_max_queries,
                    use_keyword_extraction=use_keyword_extraction,
                    keyword_cache_dir=(user_root / "keyword_cache") if user_root else keyword_cache_dir,
                    hot_cache_dir=hot_cache_dir,
                    min_view_count=min_view_count,
                    heat_source=heat_source,
                    use_llm_refilter=use_llm_refilter,
                    refilter_batch_size=refilter_batch_size,
                )
            except Exception as exc:
                logger.exception("user %s unexpected error", spec.user_id)
                return _user_failure(
                    user_id=spec.user_id,
                    error_code="internal",
                    error_detail=f"{type(exc).__name__}: {exc}",
                )

    results = await asyncio.gather(*[_one(s) for s in specs])
    return {r["user_id"]: r for r in results}


def _user_failure(
    *, user_id: str, error_code: str, error_detail: str
) -> dict[str, Any]:
    """In-memory failure payload for ``run_one_user`` / ``run_all_users``."""
    return {"user_id": user_id, "error": error_code, "error_detail": error_detail}


def _user_payload(
    *,
    user_id: str,
    track_1: str,
    track_2: str,
    persona: str,
    recommendations: list,
    searched_articles: list[dict[str, Any]],
    body_max_chars: int,
    search_query_map: dict[str, str],
    summary: str,
) -> dict[str, Any]:
    """Build the in-memory success payload for ``run_one_user``.

    Kept as a dict so the CLI and desktop runner can persist the report layout
    from the same in-memory source of truth.
    """
    return {
        "user_id": user_id,
        "input": {"track_1": track_1, "track_2": track_2, "persona": persona},
        "generated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "recommendations": [
            {
                "rank": i + 1,
                "title": r.content.title,
                "url": r.content.content_url,
                "source_url": r.content.content_url,
                "source": r.content.source_platform,
                "author": r.content.author_name or "",
                "search_query": search_query_map.get(r.content.content_id, ""),
                "heat": {
                    "view": int(r.content.view_count),
                    "like": int(r.content.like_count),
                    "comment": int(r.content.comment_count),
                    "favorite": int(r.content.favorite_count),
                    "share": int(r.content.share_count),
                    "rank": int(r.content.source_rank),
                },
                "body_text": (r.content.body_text or "")[:body_max_chars],
                "body_text_full": r.content.body_text or "",
                "body_text_length": len(r.content.body_text or ""),
                "body_truncated": len(r.content.body_text or "") > body_max_chars,
                "published_at": r.content.published_at or "",
                "fetched_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            }
            for i, r in enumerate(recommendations)
        ],
        "searched_articles": [
            {
                "rank": i + 1,
                "article_id": str(article.get("article_id") or ""),
                "title": str(article.get("title") or ""),
                "url": str(article.get("url") or ""),
                "source_url": str(article.get("source_url") or article.get("url") or ""),
                "platform": str(article.get("platform") or ""),
                "author": str(article.get("author") or ""),
                "body": str(article.get("body_text") or ""),
                "body_chars": len(str(article.get("body_text") or "")),
                "body_fetch_status": str(article.get("body_fetch_status") or ""),
                "content_type": str(article.get("content_type") or ""),
                "search_query": str(article.get("search_query") or ""),
                "published_at": str(article.get("published_at") or ""),
                "heat": article.get("heat") or {},
            }
            for i, article in enumerate(searched_articles)
        ],
        "summary": summary,
    }
