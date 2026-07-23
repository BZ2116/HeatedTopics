"""Conditional search discovery for cached news provider workflows.

This module orchestrates the user-request stage described in spec §3.2 and plan
Task 8. Given a user profile, a business date, a filesystem repository, and a
news provider, it returns up to ``MAX_RESULTS`` ``QualifiedArticle`` objects
ranked by ``platform_heat_score``.

The algorithm has three guard rails:

* Skip search when the eligible cached board already supplies at least
  ``MIN_RESULTS`` matched items.
* Cap search candidates at ``MAX_SEARCH_CANDIDATES`` unique items and at most
  ``MAX_RESULTS`` qualified items.
* Use the V1 NFKC matching semantics over title, summary, and full detail to
  remove duplicates, then delegate to ``rank_platform_articles`` for the
  final ordering so search order never determines the response order.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence
from unicodedata import normalize
from urllib.parse import unquote, urlsplit

from heated_topics_v3.contracts import (
    ContentValidation,
    HeatEvidence,
    HotItem,
    ItemDetail,
    QualifiedArticle,
    SearchCacheRecord,
    UserProfile,
)
from heated_topics_v3.heat import (
    dynamic_floors,
    qualifies_public_metrics,
    rank_platform_articles,
)
from heated_topics_v3.content import validate_full_text
from heated_topics_v3.matching import matches_primary_keyword
from heated_topics_v3.providers.common import NewsProvider
from heated_topics_v3.storage import FileRepository


MIN_RESULTS = 5
MAX_RESULTS = 20
SEARCH_PAGE_SIZE = 15
MAX_SEARCH_CANDIDATES = 60

NEGATIVE_CACHE_DURATION = timedelta(minutes=10)
SHANGHAI_TZ = timezone(timedelta(hours=8))


def discover_platform_articles(
    profile: UserProfile,
    business_date: str,
    collected_at: str,
    repository: FileRepository,
    provider: NewsProvider,
) -> tuple[QualifiedArticle, ...]:
    """Return up to ``MAX_RESULTS`` ranked articles for ``profile`` and ``provider``.

    The cached eligible board for the requested business date is preferred. If
    fewer than ``MIN_RESULTS`` matches are available, the provider's keyword
    search is used to expand the pool to at most ``MAX_SEARCH_CANDIDATES``
    unique candidates and ``MAX_RESULTS`` qualified articles.
    """

    cached = _load_cached_eligible(repository, business_date, provider.platform)
    matched = _match_articles(profile, cached)

    if len(matched) >= MIN_RESULTS:
        return _rank_with_provider(provider, matched)[:MAX_RESULTS]

    if not _has_active_search_window(collected_at, datetime.now(tz=SHANGHAI_TZ)):
        snapshot = repository.resolve_eligible_snapshot(
            provider.platform, collected_at, max_age_hours=48
        )
        if snapshot is not None:
            snapshot_date, snapshot_articles = snapshot
            snapshot_matched = _match_articles(profile, snapshot_articles)
            if len(snapshot_matched) >= MIN_RESULTS:
                return _rank_snapshot(
                    snapshot_matched, provider, snapshot_date=snapshot_date
                )

    cache = repository.load_search_cache(business_date, provider.platform, profile.primary_keyword)
    if cache is not None:
        if cache.status in {"success", "empty"}:
            cached_pool = _merge(
                matched,
                list(cache.articles),
                provider=provider,
            )
            return _rank_with_provider(provider, cached_pool)[:MAX_RESULTS]
        if cache.status == "failed":
            if _negative_cache_active(cache, collected_at):
                return _rank_cached_only(matched, provider)

    try:
        search_outcome = _run_search_discovery(
            profile=profile,
            business_date=business_date,
            collected_at=collected_at,
            repository=repository,
            provider=provider,
            seeded_matched=matched,
        )
    except Exception as error:
        repository.save_search_cache(
            business_date,
            provider.platform,
            profile.primary_keyword,
            status="failed",
            articles=(),
            rejected=(),
            collected_at=collected_at,
            retry_after=_retry_after_iso(collected_at),
        )
        return _rank_cached_only(matched, provider)

    return search_outcome


def _provider_search(
    provider: NewsProvider,
    keyword: str,
    page: int,
    page_size: int,
    collected_at: str,
    official: Sequence[QualifiedArticle],
) -> ProviderCapture:
    contextual = getattr(provider, "search_with_context", None)
    if callable(contextual):
        return contextual(keyword, page, page_size, collected_at, tuple(official))
    return provider.search(keyword, page, page_size, collected_at)


def _provider_search_evidence(
    provider: NewsProvider,
    item: HotItem,
    floors: Mapping[str, float],
) -> HeatEvidence | None:
    builder = getattr(provider, "build_search_evidence", None)
    if callable(builder):
        return builder(item, floors)
    metrics = dict(item.heat.metrics)
    qualified_by = qualifies_public_metrics(metrics, floors)
    if not metrics or not qualified_by:
        return None
    return HeatEvidence(
        source_kind="public_engagement",
        platform_rank=None,
        native_hot_value=None,
        metrics=metrics,
        threshold_metrics=dict(floors),
        qualified_by=tuple(qualified_by),
    )


def _rank_with_provider(
    provider: NewsProvider,
    articles: Sequence[QualifiedArticle],
) -> tuple[QualifiedArticle, ...]:
    ranker = getattr(provider, "rank_articles", None)
    if callable(ranker):
        return tuple(ranker(tuple(articles)))
    return rank_platform_articles(tuple(articles), provider.weights)


def _rank_cached_only(
    matched: Sequence[QualifiedArticle],
    provider: NewsProvider,
) -> tuple[QualifiedArticle, ...]:
    return _rank_with_provider(provider, matched)[:MAX_RESULTS]


def _rank_snapshot(
    matched: Sequence[QualifiedArticle],
    provider: NewsProvider,
    *,
    snapshot_date: str,
) -> tuple[QualifiedArticle, ...]:
    ranked = _rank_with_provider(provider, matched)[:MAX_RESULTS]
    return tuple(
        replace(
            article,
            hot_item=replace(
                article.hot_item,
                raw_payload={
                    **article.hot_item.raw_payload,
                    "snapshot_date": snapshot_date,
                    "is_stale": True,
                },
            ),
        )
        for article in ranked
    )


def _has_active_search_window(collected_at: str, now: datetime) -> bool:
    """Return True when the provider search window is still open for ``collected_at``.

    The search window is open only when ``collected_at`` falls on the same
    Shanghai calendar day as ``now``. Anything older (yesterday or earlier)
    means the daily collection has rolled past and the caller must fall back to
    the most recent eligible snapshot instead of issuing new provider searches.
    """

    parsed = _parse_collected_at(collected_at)
    if parsed is None:
        return False
    return parsed.date() >= now.astimezone(SHANGHAI_TZ).date()


def _load_cached_eligible(
    repository: FileRepository,
    business_date: str,
    platform: str,
) -> tuple[QualifiedArticle, ...]:
    try:
        return repository.load_eligible(business_date, platform)
    except Exception:
        return ()


def _match_articles(
    profile: UserProfile, articles: Iterable[QualifiedArticle]
) -> list[QualifiedArticle]:
    return [
        article
        for article in articles
        if matches_primary_keyword(
            profile,
            article.hot_item,
            article.detail,
        )
    ]


def _run_search_discovery(
    *,
    profile: UserProfile,
    business_date: str,
    collected_at: str,
    repository: FileRepository,
    provider: NewsProvider,
    seeded_matched: Sequence[QualifiedArticle],
) -> tuple[QualifiedArticle, ...]:
    floors = _dynamic_floors_from_seeded(seeded_matched, provider)

    candidate_pool: dict[str, HotItem] = {}
    rejected_candidates: list[dict[str, Any]] = []
    qualified_search: list[QualifiedArticle] = []
    unique_candidates = 0
    page = 1
    stop_reason: str = ""
    max_pages = MAX_SEARCH_CANDIDATES // SEARCH_PAGE_SIZE + 1

    while (
        page <= max_pages
        and len(qualified_search) < MAX_RESULTS
        and unique_candidates < MAX_SEARCH_CANDIDATES
    ):
        capture = _provider_search(
            provider,
            profile.primary_keyword,
            page,
            SEARCH_PAGE_SIZE,
            collected_at,
            seeded_matched,
        )
        page += 1
        if not capture.items:
            stop_reason = "empty_page"
            break
        page_new_candidates = 0
        for item in capture.items:
            key = _deduplication_key(item)
            if not key or key in candidate_pool:
                continue
            candidate_pool[key] = item
            unique_candidates += 1
            page_new_candidates += 1
            if unique_candidates >= MAX_SEARCH_CANDIDATES:
                break

        if unique_candidates >= MAX_SEARCH_CANDIDATES:
            stop_reason = stop_reason or "candidate_limit"
        if page_new_candidates == 0:
            stop_reason = stop_reason or "duplicate_only"
            break

        page_items = list(candidate_pool.values())[-(page_new_candidates):]
        enriched_items = list(provider.enrich_metrics(page_items, collected_at))
        for enriched, original in zip(enriched_items, page_items):
            if enriched is not original:
                candidate_pool[original.item_id] = enriched
        page_items = enriched_items

        for item in page_items:
            if len(qualified_search) >= MAX_RESULTS:
                break
            if not matches_primary_keyword(profile, item, None):
                rejected_candidates.append(
                    {
                        "item_id": item.item_id,
                        "source_url": item.url,
                        "reasons": ["rejected:keyword_prefilter"],
                    }
                )
                continue
            detail = _safe_fetch_detail(provider, item, collected_at)
            evidence = _provider_search_evidence(provider, item, floors)
            if evidence is None:
                metrics = dict(item.heat.metrics)
                if not metrics:
                    rejected_candidates.append(
                        {
                            "item_id": item.item_id,
                            "source_url": item.url,
                            "reasons": ["rejected:no_metric"],
                        }
                    )
                    continue
                public_qualified = qualifies_public_metrics(metrics, floors)
                if not public_qualified:
                    rejected_candidates.append(
                        {
                            "item_id": item.item_id,
                            "source_url": item.url,
                            "reasons": ["rejected:below_floor"],
                        }
                    )
                    continue
                evidence = HeatEvidence(
                    source_kind="public_engagement",
                    platform_rank=None,
                    native_hot_value=None,
                    metrics=metrics,
                    threshold_metrics=dict(floors),
                    qualified_by=tuple(public_qualified),
                )

            content = detail.content if detail else ""
            parser = ""
            if detail is not None and detail.fetch_status.startswith("rejected"):
                parser = detail.fetch_status.split(":", 1)[-1]
            validation = validate_full_text(
                content, item.title, item.summary, parser=parser
            )
            if (
                detail is None
                or detail.content_status != "full_text"
                or validation.status != "accepted"
            ):
                rejected_candidates.append(
                    {
                        "item_id": item.item_id,
                        "source_url": item.url,
                        "reasons": list(validation.reasons or ["rejected:no_body"]),
                    }
                )
                continue

            qualified_search.append(
                QualifiedArticle(
                    hot_item=item,
                    detail=detail,
                    heat_evidence=evidence,
                    content_validation=ContentValidation(
                        status=validation.status,
                        parser=validation.parser,
                        character_count=validation.character_count,
                        paragraph_count=validation.paragraph_count,
                        reasons=validation.reasons,
                    ),
                    platform_heat_score=0.0,
                )
            )
        if len(qualified_search) >= MAX_RESULTS:
            stop_reason = stop_reason or "qualified_limit"
            break

    if not stop_reason:
        stop_reason = "pages_exhausted"

    repository.save_rejected(
        business_date,
        provider.platform,
        rejected_candidates,
    )
    repository.save_search_cache(
        business_date,
        provider.platform,
        profile.primary_keyword,
        status="success" if qualified_search else "empty",
        articles=tuple(qualified_search),
        rejected=tuple(rejected_candidates),
        collected_at=collected_at,
    )
    return _merge(seeded_matched, qualified_search, provider=provider)


def _safe_fetch_detail(
    provider: NewsProvider, item: HotItem, collected_at: str
) -> ItemDetail | None:
    try:
        return provider.fetch_detail(item, collected_at)
    except Exception:
        return ItemDetail(
            item_id=item.item_id,
            content="",
            content_status="rejected",
            publication_time=item.publication_time,
            collected_at=collected_at,
            source_url=item.url,
            fetch_status="rejected:fetch_error",
        )


def _dynamic_floors_from_seeded(
    matched: Sequence[QualifiedArticle],
    provider: NewsProvider,
) -> dict[str, float]:
    board_metrics = [dict(article.heat_evidence.metrics) for article in matched]
    floors = dynamic_floors(board_metrics, provider.absolute_floors)
    if floors:
        return floors
    return {metric: float(value) for metric, value in provider.absolute_floors.items()}


def _merge(
    cached: Sequence[QualifiedArticle],
    incoming: Sequence[QualifiedArticle],
    *,
    provider: NewsProvider,
) -> tuple[QualifiedArticle, ...]:
    merged: dict[str, QualifiedArticle] = {}

    for article in cached:
        key = _article_dedup_key(article.hot_item)
        merged[key] = article

    for article in incoming:
        key = _article_dedup_key(article.hot_item)
        if key not in merged:
            merged[key] = article
            continue
        merged[key] = _merge_articles(merged[key], article)

    pool = list(merged.values())
    return _rank_with_provider(provider, pool)[:MAX_RESULTS]


def _merge_articles(
    primary: QualifiedArticle, duplicate: QualifiedArticle
) -> QualifiedArticle:
    """Merge duplicates preserving official evidence, max metrics, full text."""

    def _is_official(article: QualifiedArticle) -> bool:
        return article.heat_evidence.source_kind == "official_hot_board"

    keep_official = _is_official(primary) or not _is_official(duplicate)
    base = primary if keep_official else duplicate
    other = duplicate if keep_official else primary

    merged_metrics: dict[str, float] = {}
    for key in set(base.heat_evidence.metrics) | set(other.heat_evidence.metrics):
        values = [
            float(base.heat_evidence.metrics.get(key, 0.0)),
            float(other.heat_evidence.metrics.get(key, 0.0)),
        ]
        merged_metrics[key] = max(values)

    platform_ranks = [
        rank
        for rank in (primary.heat_evidence.platform_rank, duplicate.heat_evidence.platform_rank)
        if rank is not None and rank > 0
    ]
    platform_rank = min(platform_ranks) if platform_ranks else None

    qualified_by = primary.heat_evidence.qualified_by + tuple(
        metric
        for metric in duplicate.heat_evidence.qualified_by
        if metric not in primary.heat_evidence.qualified_by
    )
    if not qualified_by:
        qualified_by = ("official_hot_board",) if _is_official(base) else ("public_engagement",)

    native_hot = base.heat_evidence.native_hot_value or other.heat_evidence.native_hot_value
    evidence = HeatEvidence(
        source_kind=base.heat_evidence.source_kind,
        platform_rank=platform_rank,
        native_hot_value=native_hot,
        metrics=merged_metrics,
        threshold_metrics=base.heat_evidence.threshold_metrics or other.heat_evidence.threshold_metrics,
        qualified_by=tuple(qualified_by),
    )

    preferred_detail = base.detail if base.detail.content_status == "full_text" else other.detail
    other_detail = other.detail if preferred_detail is base.detail else base.detail
    if other_detail.content_status == "full_text" and (
        preferred_detail.content_status != "full_text"
        or len(other_detail.content) > len(preferred_detail.content)
    ):
        preferred_detail = other_detail

    hot_item = base.hot_item
    if base.hot_item.url != other.hot_item.url:
        canonical = _canonical_url(other.hot_item.url) or _canonical_url(base.hot_item.url)
        if canonical:
            hot_item = replace(hot_item, url=f"https://{canonical}")

    validation = base.content_validation
    other_validation = other.content_validation
    if (
        validation.status != "accepted"
        or other_validation.status == "accepted"
        and other_validation.character_count > validation.character_count
    ):
        validation = other_validation

    return QualifiedArticle(
        hot_item=hot_item,
        detail=preferred_detail,
        heat_evidence=evidence,
        content_validation=validation,
        platform_heat_score=base.platform_heat_score,
    )


def _negative_cache_active(
    cache: SearchCacheRecord, collected_at: str
) -> bool:
    retry_after = cache.retry_after
    if not retry_after:
        return False
    parsed_cache = _parse_collected_at(cache.collected_at) or datetime.now(tz=SHANGHAI_TZ)
    parsed_now = _parse_collected_at(collected_at) or datetime.now(tz=SHANGHAI_TZ)
    parsed_retry = _parse_collected_at(retry_after)
    if parsed_retry is None:
        return False
    if parsed_now < parsed_retry:
        return True
    return (parsed_now - parsed_cache) < NEGATIVE_CACHE_DURATION


def _retry_after_iso(collected_at: str) -> str:
    parsed = _parse_collected_at(collected_at) or datetime.now(tz=SHANGHAI_TZ)
    return (parsed + NEGATIVE_CACHE_DURATION).isoformat()


def _deduplication_key(item: HotItem) -> str:
    return _article_dedup_key(item)


def _article_dedup_key(item: HotItem) -> str:
    if item.item_id and item.item_id.strip():
        return f"id::{normalize('NFKC', item.item_id).casefold().strip()}"
    canonical = _canonical_url(item.url)
    if canonical:
        return f"url::{canonical}"
    title = _normalize_text(item.title)
    if title:
        return f"title::{title}"
    return ""


def _canonical_url(value: str) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(parsed.path).rstrip("/")
    if not path:
        return None
    return f"{host}{path}"


def _normalize_text(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())


def _parse_collected_at(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)
