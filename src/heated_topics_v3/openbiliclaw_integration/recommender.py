"""Per-user recommendation orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from heated_topics_v3.clock import SHANGHAI
from heated_topics_v3.contracts import HotItem, ItemDetail
from heated_topics_v3.openbiliclaw_integration import (
    candidate_adapter,
    last30days_adapter,
    last30days_source,
    output,
    runtime,
    user_profile,
)

logger = logging.getLogger(__name__)


# Re-export for convenience so tests can patch via `recommender.load_users`.
load_users = user_profile.load_users


# Default provider list (ordered by typical relevance for V3 hot topics).
# ``dailyhot:<route>`` syntax dispatches to DailyHotApiProvider — e.g.
# ``dailyhot:36kr`` for 36氪, ``dailyhot:sspai`` for 少数派. Hot-list data
# comes from data/cache/dailyhot/*.json (written by the upstream dailyhot
# client); article bodies are fetched per-URL via GNE.
_DEFAULT_PROVIDERS: tuple[str, ...] = (
    "juejin",
    "toutiao",
    "baidu_hot",
    "zhihu_hot",
    "zhihu_daily",
    "sina_news",
    "thepaper",
    "netease_news",
)


# Detail fetch cap per platform: collecting full bodies for 50 items is too
# slow and blocks the hot list. We only need bodies for the candidates the
# engine actually considers.
_DETAIL_FETCH_CAP = 20


# Search-enabled providers (no API key required, returns content actually
# matching a keyword — not just whatever is on the hot board today). Order
# matters only for tie-breaks. ``baidu_hot`` and ``zhihu_hot`` are excluded
# because they need credentials / return captcha-blocked pages.
_SEARCH_PROVIDERS: tuple[str, ...] = (
    "toutiao",
    "sina_news",
    "thepaper",
    "zhihu_daily",
)

# Per user: take the top-K interests (by weight) and search each on each
# search-enabled provider. 3 × 4 = 12 (provider, interest) pairs; with
# 5 results each = up to 60 search candidates per user. After URL-dedup
# against ~250 hot-list candidates this typically lands around 80-100
# unique items, well within the engine's filter budget.
_SEARCH_TOP_K_INTERESTS = 3
_SEARCH_RESULTS_PER_INTEREST = 5
# Full-body fetches are slow (HTTP + GNE per article). Cap per
# (provider, interest) pair so total stays bounded: 3 × 4 × 3 = 36 fetches
# per user worst case.
_SEARCH_DETAIL_FETCH_CAP_PER_INTEREST = 3


def _build_provider(platform: str) -> Any | None:
    """Instantiate the V3 provider class for ``platform``.

    Returns None if the platform name is unknown so the caller can skip it.
    """
    import httpx as _httpx

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

        return ZhihuHotProvider(client, ""), client
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
    elif item.summary:
        body_text = item.summary
    heat_dict: dict[str, Any] = {}
    if item.heat.value is not None:
        # Map the native metric to a "view"-like key for adapter visibility.
        heat_dict["view"] = int(item.heat.value)
    if item.heat.metrics:
        for k, v in item.heat.metrics.items():
            heat_dict.setdefault(k, int(v))
    heat_dict["rank"] = item.rank or 0
    return {
        "article_id": item.item_id,
        "title": item.title,
        "url": item.url,
        "body_text": body_text,
        "summary": item.summary or "",
        "author": "",
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


def _is_hot_relevant(article: dict[str, Any], interests: Any) -> bool:
    """Loose relevance: any interest name appears in title/body/summary.

    Cheap stand-in for "does this hot-list item actually match what the
    user cares about". Embedding similarity would be more accurate but
    costs an extra LLM/embedding round-trip per hot item; the keyword
    check is a 0-cost filter that catches obvious mismatches like
    "解放军警告" vs interests = ["非遗", "地方习俗"…].
    """
    if not interests:
        return False
    title = article.get("title") or ""
    body_text = article.get("body_text") or ""
    summary = article.get("summary") or ""
    haystack = f"{title} {body_text} {summary}".lower()
    if not haystack.strip():
        return False
    return any(i.name.lower() in haystack for i in interests)


def _rebalance_pool(
    hot: list[dict[str, Any]],
    search: list[dict[str, Any]],
    interests: Any,
    target_limit: int,
    prefer_search: bool,
) -> list[dict[str, Any]]:
    """Build the final candidate pool. Search is trusted over hot when
    prefer_search=True; hot-list items that don't mention the user's
    interests are dropped so the engine's MMR doesn't get pulled back to
    generic-news top picks.
    """
    if not prefer_search:
        return hot + search
    relevant_hot = [a for a in hot if _is_hot_relevant(a, interests)]
    other_hot = [a for a in hot if not _is_hot_relevant(a, interests)]
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
    target_limit: int = 10,
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
            cap_items = items[:_DETAIL_FETCH_CAP]
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
    if use_search and spec.interests:
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
            top_interests = sorted(
                spec.interests, key=lambda i: i.weight, reverse=True
            )[:search_top_k]
            logger.info(
                "search pass: providers=%s interests=%s",
                search_enabled,
                [i.name for i in top_interests],
            )
            for platform in search_enabled:
                built = _build_provider(platform)
                if built is None:
                    continue
                provider, client = built
                try:
                    for interest in top_interests:
                        try:
                            capture = _call_provider_search(
                                provider,
                                platform,
                                interest.name,
                                search_results_per_interest,
                                collected_at,
                            )
                            items = capture.items[:search_results_per_interest]
                        except Exception as exc:
                            logger.warning(
                                "search %s(%s) failed: %s",
                                platform,
                                interest.name,
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
                                article["search_query"] = interest.name
                            _add_to(search_articles, article)
                        for item in items[_SEARCH_DETAIL_FETCH_CAP_PER_INTEREST:]:
                            article = _hotitem_to_article(item, None, platform)
                            if article is not None:
                                article["search_query"] = interest.name
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
            spec.interests,
            target_limit=target_limit,
            prefer_search=prefer_search,
        )
    return hot_articles


# --- last30days source support ----------------------------------------------


def _first_interest_name(spec: user_profile.UserSpec) -> str:
    """Return the highest-weight interest name, or '' if none."""
    if not spec.interests:
        return ""
    return max(spec.interests, key=lambda i: i.weight).name


def _fetch_last30days_candidates(
    spec: user_profile.UserSpec,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Invoke last30days CLI for one user; return V3 article dicts.

    Pipeline: subprocess → parse JSON → adapter (Item → HotItem/ItemDetail)
    → ``_hotitem_to_article`` (existing V3 internal mapper). The returned
    list is in the same shape as ``fetch_candidates``, so downstream code
    needs no awareness of which source produced each article.
    """
    cli_path = Path(cfg["cli_path"])
    query = cfg.get("query") or spec.user_id  # fallback chain handled below
    if not query:
        query = _first_interest_name(spec)
    if not query:
        logger.warning("user %s: no query for last30days, skipping", spec.user_id)
        return []

    save_dir = Path(cfg.get("save_dir", "data/last30days")) / spec.user_id
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
        logger.warning("user %s: last30days fetch failed: %s", spec.user_id, exc)
        return []

    items, details = last30days_adapter.to_hot_items(report)
    articles: list[dict[str, Any]] = []
    for item, detail in zip(items, details):
        article = _hotitem_to_article(item, detail, item.platform)
        if article is not None:
            articles.append(article)
    return articles


def _fetch_candidates_for_user(
    spec: user_profile.UserSpec,
    *,
    source: str,
    last30days_config: dict[str, Any] | None,
    target_limit: int = 10,
    v3_providers: list[str] | None = None,
    use_search: bool = True,
    prefer_search: bool = True,
    search_providers: list[str] | None = None,
    search_top_k: int = _SEARCH_TOP_K_INTERESTS,
    search_results_per_interest: int = _SEARCH_RESULTS_PER_INTEREST,
) -> list[dict[str, Any]]:
    """Dispatch candidate fetching based on ``source``.

    - ``v3-hotlist``: only V3 providers (default; preserves existing behaviour).
    - ``last30days``: only last30days CLI (requires ``last30days_config``).
    - ``both``: V3 first, last30days second with URL dedup (V3 wins ties).
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
            l30 = _fetch_last30days_candidates(spec, last30days_config)
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
            api_key=os.environ["OPENBILICLAW_LLM_API_KEY"],
            model="MiniMax-M2.7",
            base_url="https://api.minimaxi.com/v1",
        )
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"
    elif not config.llm.embedding.provider.strip():
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"

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
) -> dict[str, Any]:
    """Async body of run_one_user."""
    articles = _fetch_candidates_for_user(
        spec,
        source=source,
        last30days_config=last30days_config,
        target_limit=limit,
        v3_providers=providers,
        use_search=use_search,
        prefer_search=prefer_search,
        search_providers=search_providers,
        search_top_k=search_top_k,
        search_results_per_interest=search_results_per_interest,
    )
    if not articles:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="no_candidates",
            error_detail=f"Fetched 0 articles from providers={providers or 'all'}",
        )
    candidates = candidate_adapter.to_discovered(
        articles,
        platform=articles[0].get("platform", "juejin")
        if isinstance(articles[0], dict) and "platform" in articles[0]
        else "juejin",
    )
    # If articles don't carry 'platform' per-item, attribute by provider list order.
    if not any(isinstance(a, dict) and "platform" in a for a in articles):
        if providers and len(providers) == 1:
            candidates = candidate_adapter.to_discovered(
                articles, platform=providers[0]
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
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="timeout",
            error_detail=f"exceeded {per_user_timeout}s",
        )
    except Exception as exc:
        logger.exception("user %s: engine failed", spec.user_id)
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="engine_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    if not recommendations:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="no_recommendations",
            error_detail="Engine returned 0 recommendations",
        )
    return output.format_user_file(
        user_id=spec.user_id,
        track_1=spec.track_1,
        track_2=spec.track_2,
        persona=spec.persona,
        recommendations=recommendations,
        body_max_chars=body_max_chars,
    )


def run_one_user(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int = 5,
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
) -> dict[str, Any]:
    """Synchronous wrapper around _run_one_user_async."""
    return asyncio.run(
        _run_one_user_async(
            spec,
            data_dir=data_dir,
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
        )
    )


async def run_all_users(
    *,
    specs: list[user_profile.UserSpec],
    data_dir: Path,
    max_parallel: int = 5,
    limit: int = 5,
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
) -> dict[str, dict[str, Any]]:
    """Run recommendation for all users. Returns {user_id: payload}.

    v2: takes pre-loaded specs (caller loads from xlsx via excel_loader).
    Returns dict keyed by user_id so CLI can write per-user files without
    re-correlating with the input list.
    """
    if shared_runtime is None and config_path is not None:
        shared_runtime = _build_shared_runtime(
            shared_data_dir=data_dir,
            config_path=config_path,
        )
    sem = asyncio.Semaphore(max_parallel)

    async def _one(spec: user_profile.UserSpec) -> dict[str, Any]:
        async with sem:
            try:
                return await _run_one_user_async(
                    spec,
                    data_dir=data_dir,
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
                )
            except Exception as exc:
                logger.exception("user %s unexpected error", spec.user_id)
                return output.format_user_failure(
                    user_id=spec.user_id,
                    error_code="internal",
                    error_detail=f"{type(exc).__name__}: {exc}",
                )

    results = await asyncio.gather(*[_one(s) for s in specs])
    return {r["user_id"]: r for r in results}
