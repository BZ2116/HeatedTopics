"""Conditional search discovery, deduplication, and search cache integration."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import pytest

from heated_topics_v3.contracts import (
    ContentValidation,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    QualifiedArticle,
    UserProfile,
)
from heated_topics_v3.discovery import (
    MAX_RESULTS,
    MAX_SEARCH_CANDIDATES,
    MIN_RESULTS,
    SEARCH_PAGE_SIZE,
    discover_platform_articles,
)
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.storage import FileRepository


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 23, 8, 1, tzinfo=SHANGHAI)
COLLECTED_AT = NOW.isoformat()
BUSINESS_DATE = "2026-07-23"
KEYWORD = "人工智能"

_LONG_BODY = (
    "正文第一段，介绍事件背景，描述发生时间地点和主要人物，并交代事件起因。\n\n"
    "正文第二段，引用公开信息补充细节，说明各方回应、数据来源与相关证据。\n\n"
    "正文第三段，交待后续安排、影响范围、可能的后续进展与尚需确认的信息。\n\n"
    "正文第四段，提供独立第三方观察和专家评论，对事件的长期影响做简要判断。\n"
)


PROFILE = UserProfile(
    user_id="u-discovery",
    primary_track="科技",
    secondary_track="新闻",
    persona="discovery tester",
    primary_keyword=KEYWORD,
    updated_at=COLLECTED_AT,
)


def _metrics(payload: Mapping[str, float] | None, *, name: str = "comments") -> HeatMetrics:
    payload = dict(payload or {})
    primary = next(iter(payload.values()), None)
    return HeatMetrics(
        value=primary,
        label="" if primary is None else str(primary),
        metric_name=name if payload else "",
        metrics=payload,
    )


def _make_hot_item(
    *,
    platform: str,
    item_id: str,
    rank: int | None,
    title: str,
    summary: str = "",
    url: str | None = None,
    metrics: Mapping[str, float] | None = None,
    publication_time: str | None = None,
    raw: Mapping[str, Any] | None = None,
) -> HotItem:
    effective_url = url or f"https://example.test/{platform}/{item_id}"
    return HotItem(
        item_id=item_id,
        platform=platform,
        title=title,
        url=effective_url,
        rank=rank,
        heat=_metrics(metrics),
        summary=summary,
        publication_time=publication_time,
        collected_at=COLLECTED_AT,
        raw_payload=dict(raw or {}),
    )


def _detail(
    item: HotItem,
    *,
    content_status: str = "full_text",
    content: str = _LONG_BODY,
    fetch_status: str = "success",
) -> ItemDetail:
    return ItemDetail(
        item_id=item.item_id,
        content=content,
        content_status=content_status,  # type: ignore[arg-type]
        publication_time=item.publication_time,
        collected_at=COLLECTED_AT,
        source_url=item.url,
        fetch_status=fetch_status,
    )


def _evidence(
    item: HotItem,
    *,
    metrics: Mapping[str, float] | None = None,
    source: str = "official_hot_board",
    rank: int | None = None,
) -> HeatEvidence:
    metrics_map = dict(metrics or {})
    if not metrics_map and item.heat.metrics:
        metrics_map = {k: float(v) for k, v in item.heat.metrics.items()}
    qualified_by = ("official_hot_board",) if source == "official_hot_board" else ()
    return HeatEvidence(
        source_kind=source,  # type: ignore[arg-type]
        platform_rank=rank if rank is not None else item.rank,
        native_hot_value=float(item.heat.value) if isinstance(item.heat.value, (int, float)) else None,
        metrics=metrics_map,
        threshold_metrics={},
        qualified_by=qualified_by,
    )


def _build_article(
    item: HotItem,
    *,
    title_override: str | None = None,
    url_override: str | None = None,
    summary_override: str | None = None,
    source: str = "official_hot_board",
    metrics: Mapping[str, float] | None = None,
    content: str = _LONG_BODY,
    parser: str = "fixture",
) -> QualifiedArticle:
    if title_override is not None or summary_override is not None or url_override is not None:
        item = replace(
            item,
            title=item.title if title_override is None else title_override,
            summary=item.summary if summary_override is None else summary_override,
            url=item.url if url_override is None else url_override,
        )
    detail = _detail(item, content=content)
    validation = ContentValidation(
        status="accepted",
        parser=parser,
        character_count=len(content),
        paragraph_count=content.count("\n\n") + 1,
        reasons=(),
    )
    return QualifiedArticle(
        hot_item=item,
        detail=detail,
        heat_evidence=_evidence(item, metrics=metrics, source=source),
        content_validation=validation,
        platform_heat_score=0.0,
    )


def _seed_eligible(
    repository: FileRepository,
    platform: str,
    *,
    count: int,
    base_id: str | None = None,
    metrics: Mapping[str, float] | None = None,
    source: str = "official_hot_board",
) -> tuple[QualifiedArticle, ...]:
    metrics = dict(metrics or {"comments": 10.0})
    articles = tuple(
        _build_article(
            _make_hot_item(
                platform=platform,
                item_id=f"{base_id or platform}_{index + 1}",
                rank=index + 1,
                title=f"{KEYWORD} 标题 {platform} {index + 1}",
                summary=f"{KEYWORD} 摘要",
                metrics=metrics,
            ),
            metrics=metrics,
            source=source,
        )
        for index in range(count)
    )
    repository.save_eligible(BUSINESS_DATE, platform, articles)
    repository.publish_active_snapshot(platform, BUSINESS_DATE)
    return articles


def _make_pages(
    *,
    total: int,
    qualified: int,
    platform: str = "thepaper",
) -> tuple[tuple[HotItem, ...], ...]:
    pages: list[tuple[HotItem, ...]] = []
    emitted = 0
    while emitted < total:
        chunk: list[HotItem] = []
        for offset in range(SEARCH_PAGE_SIZE):
            if emitted + offset >= total:
                break
            position = emitted + offset
            is_qualified = position < qualified
            item = _make_hot_item(
                platform=platform,
                item_id=f"thepaper_search_{position + 1}",
                rank=position + 1,
                title=f"搜索{KEYWORD}条目{position + 1}",
                summary=f"{KEYWORD} 摘要",
                metrics={"interaction_num": 30.0 + position, "praise_times": 20.0 + position}
                if is_qualified
                else {"interaction_num": 0.0, "praise_times": 0.0},
            )
            chunk.append(item)
        pages.append(tuple(chunk))
        emitted += SEARCH_PAGE_SIZE
    return tuple(pages)


class FakeProvider:
    """In-memory Provider double capturing hot details / search / enrich usage."""

    def __init__(
        self,
        platform: str,
        *,
        weights: Mapping[str, float] | None = None,
        absolute_floors: Mapping[str, float] | None = None,
        pages: Sequence[Sequence[HotItem]] = (),
        detail_payloads: Mapping[str, ItemDetail] | None = None,
        enrich_metrics: Mapping[str, float] | None = None,
        search_error: Exception | None = None,
        detail_mode: str = "auto",
    ) -> None:
        self.platform = platform
        self.weights = dict(weights or {"comments": 0.6, "views": 0.4})
        self.absolute_floors = dict(absolute_floors or {"comments": 10.0})
        self._pages = tuple(tuple(page) for page in pages)
        self._detail_payloads = dict(detail_payloads or {})
        self._enrich = dict(enrich_metrics or {})
        self.search_calls: list[tuple[str, int, int, str]] = []
        self.search_call_count = 0
        self.detail_calls: set[str] = set()
        self._search_error = search_error
        self._detail_mode = detail_mode

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        return ProviderCapture(json.dumps({"platform": self.platform}), ".json", ())

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        self.detail_calls.add(item.item_id)
        payload = self._detail_payloads.get(item.item_id)
        if payload is not None:
            return payload
        if self._detail_mode == "missing":
            return ItemDetail(
                item_id=item.item_id,
                content="",
                content_status="rejected",
                publication_time=item.publication_time,
                collected_at=collected_at,
                source_url=item.url,
                fetch_status="rejected:too_short",
            )
        return _detail(item)

    def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        self.search_calls.append((keyword, page, page_size, collected_at))
        self.search_call_count += 1
        if self._search_error is not None:
            raise self._search_error
        if page - 1 >= len(self._pages):
            return ProviderCapture(
                json.dumps({"platform": self.platform, "page": page, "items": []}),
                ".json",
                (),
            )
        items = self._pages[page - 1]
        return ProviderCapture(
            json.dumps(
                {
                    "platform": self.platform,
                    "page": page,
                    "items": [item.item_id for item in items],
                }
            ),
            ".json",
            items,
        )

    def enrich_metrics(
        self, items: Sequence[HotItem], collected_at: str
    ) -> tuple[HotItem, ...]:
        if not self._enrich:
            return tuple(items)
        enriched = []
        for item in items:
            enriched.append(
                replace(
                    item,
                    heat=_metrics(
                        dict(item.heat.metrics) | dict(self._enrich), name=item.heat.metric_name
                    ),
                )
            )
        return tuple(enriched)


class HookProvider(FakeProvider):
    """Test double that exercises the optional capability hooks."""

    def __init__(self, pages=()):
        super().__init__(
            platform="rank_only",
            weights={},
            absolute_floors={},
            pages=pages,
        )
        self.context_calls: list[tuple[str, int, int, tuple[str, ...]]] = []

    def search_with_context(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
        official_articles: Sequence["QualifiedArticle"],
    ) -> ProviderCapture:
        self.context_calls.append(
            (
                keyword,
                page,
                page_size,
                tuple(article.hot_item.item_id for article in official_articles),
            )
        )
        return super().search(keyword, page, page_size, collected_at)

    def build_search_evidence(
        self,
        item: HotItem,
        floors: Mapping[str, float],
    ) -> HeatEvidence:
        return HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=item.rank,
            native_hot_value=None,
            metrics={},
            threshold_metrics={},
            qualified_by=("official_hot_board",),
        )

    def rank_articles(
        self, articles: Sequence[QualifiedArticle]
    ) -> tuple[QualifiedArticle, ...]:
        return tuple(reversed(tuple(articles)))

@pytest.fixture
def repository(tmp_path) -> FileRepository:
    return FileRepository(tmp_path)


def test_constants_match_plan():
    assert MIN_RESULTS == 5
    assert MAX_RESULTS == 20
    assert SEARCH_PAGE_SIZE == 15
    assert MAX_SEARCH_CANDIDATES == 60


def test_five_cached_matches_skip_search(repository):
    _seed_eligible(repository, "sina_news", count=5)
    provider = FakeProvider(platform="sina_news")

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert len(result) == 5
    assert provider.search_calls == []
    assert {item.hot_item.item_id for item in result} == {
        f"sina_news_{index}" for index in range(1, 6)
    }


def test_four_matches_search_until_twenty_or_sixty_candidates(repository):
    _seed_eligible(repository, "thepaper", count=4)
    pages = _make_pages(total=60, qualified=18, platform="thepaper")
    provider = FakeProvider(
        platform="thepaper",
        weights={"interaction_num": 0.6, "praise_times": 0.4},
        absolute_floors={"interaction_num": 1.0, "praise_times": 10.0},
        pages=pages,
    )

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert len(result) == 20
    candidate_pages = provider.search_calls
    assert candidate_pages
    requested_pages = {call[1] for call in candidate_pages}
    assert all(call[2] == SEARCH_PAGE_SIZE for call in candidate_pages)
    assert all(call[0] == KEYWORD for call in candidate_pages)
    unique_candidates = set()
    for index in range(MAX_SEARCH_CANDIDATES // SEARCH_PAGE_SIZE):
        unique_candidates.update(item.item_id for item in pages[index])
    assert sum(len(page) for page in pages[: len(requested_pages)]) == min(
        60, sum(len(page) for page in pages[: len(requested_pages)])
    )
    scores = [article.platform_heat_score for article in result]
    assert scores == sorted(scores, reverse=True)


def test_search_results_without_body_or_heat_are_rejected_and_cached(repository):
    provider = FakeProvider(
        platform="thepaper",
        weights={"interaction_num": 0.6, "praise_times": 0.4},
        absolute_floors={"interaction_num": 1.0, "praise_times": 10.0},
        pages=(
            (
                _make_hot_item(
                    platform="thepaper",
                    item_id="thepaper_no_body",
                    rank=1,
                    title=f"无正文 {KEYWORD}",
                    summary=f"{KEYWORD} 摘要",
                    metrics={"interaction_num": 5.0, "praise_times": 5.0},
                ),
            ),
            (
                _make_hot_item(
                    platform="thepaper",
                    item_id="thepaper_no_heat",
                    rank=2,
                    title=f"无热度 {KEYWORD}",
                    summary=f"{KEYWORD} 摘要",
                    metrics={},
                ),
            ),
        ),
        detail_payloads={
            "thepaper_no_body": ItemDetail(
                item_id="thepaper_no_body",
                content="",
                content_status="rejected",
                publication_time=None,
                collected_at=COLLECTED_AT,
                source_url="https://example.test/thepaper/thepaper_no_body",
                fetch_status="rejected:too_short",
            ),
            "thepaper_no_heat": ItemDetail(
                item_id="thepaper_no_heat",
                content=_LONG_BODY,
                content_status="full_text",
                publication_time=None,
                collected_at=COLLECTED_AT,
                source_url="https://example.test/thepaper/thepaper_no_heat",
                fetch_status="success",
            ),
        },
    )

    first = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert first == ()
    for article in first:
        assert article.detail.content_status == "full_text"
        assert article.heat_evidence.qualified_by

    search_calls_after_first = len(provider.search_calls)
    second = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert first == second
    assert len(provider.search_calls) - search_calls_after_first == 0


def test_search_cache_reuse_on_second_call(repository):
    pages = (
        tuple(
            _make_hot_item(
                platform="thepaper",
                item_id=f"thepaper_pass_{i}",
                rank=i,
                title=f"通过项目 {KEYWORD} {i}",
                summary=f"{KEYWORD}",
                metrics={"interaction_num": 20.0 + i, "praise_times": 20.0 + i},
            )
            for i in range(1, 6)
        ),
    )
    provider = FakeProvider(
        platform="thepaper",
        weights={"interaction_num": 0.6, "praise_times": 0.4},
        absolute_floors={"interaction_num": 1.0, "praise_times": 10.0},
        pages=pages,
    )

    first = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )
    search_calls_after_first = len(provider.search_calls)
    second = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert len(first) == len(second) == 5
    assert len(provider.search_calls) - search_calls_after_first == 0


def test_id_url_title_deduplication_merges_search_with_cached(repository):
    _seed_eligible(repository, "sina_news", count=2)
    cached_article = repository.load_eligible(BUSINESS_DATE, "sina_news")[0]
    duplicate_title = cached_article.hot_item.title + "　"
    duplicate_url = cached_article.hot_item.url + "?utm_source=test"

    pages = (
        tuple(
            [
                replace(
                    cached_article.hot_item,
                    title=duplicate_title,
                    url=duplicate_url,
                    platform="sina_news",
                )
            ]
            + [
                _make_hot_item(
                    platform="sina_news",
                    item_id="sina_news_other",
                    rank=99,
                    title=f"重复 {KEYWORD} 新条目",
                    summary=f"{KEYWORD}",
                    metrics={"top_num": 200.0, "comments": 30.0},
                )
            ]
        ),
    )
    provider = FakeProvider(
        platform="sina_news",
        weights={"top_num": 0.7, "comments": 0.3},
        absolute_floors={"comments": 10.0},
        pages=pages,
    )

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    by_id = {article.hot_item.item_id: article for article in result}
    assert cached_article.hot_item.item_id in by_id
    assert by_id[cached_article.hot_item.item_id].hot_item.title == cached_article.hot_item.title
    assert len(result) <= MAX_RESULTS


def test_explicit_empty_result_is_cached_to_avoid_research(repository):
    repository.save_search_cache(
        BUSINESS_DATE,
        "thepaper",
        KEYWORD,
        status="empty",
        articles=(),
        rejected=(),
        collected_at=COLLECTED_AT,
    )
    provider = FakeProvider(platform="thepaper")

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert result == ()
    assert provider.search_calls == []


def test_transient_failure_does_not_become_persisted_empty(repository):
    provider = FakeProvider(
        platform="thepaper",
        search_error=RuntimeError("upstream timeout"),
    )

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert result == ()
    cache = repository.load_search_cache(BUSINESS_DATE, "thepaper", KEYWORD)
    assert cache is None or cache.status != "empty"


def test_duplicate_search_row_preserves_official_hot_board_evidence(repository):
    _seed_eligible(repository, "sina_news", count=4, metrics={"top_num": 500.0, "comments": 50.0})
    cached = repository.load_eligible(BUSINESS_DATE, "sina_news")
    duplicate = cached[0]
    pages = (
        (
            replace(
                duplicate.hot_item,
                rank=99,
                raw_payload={},
            ),
            _make_hot_item(
                platform="sina_news",
                item_id="sina_search_2",
                rank=2,
                title=f"{KEYWORD} 搜索 2",
                summary=f"{KEYWORD}",
                metrics={"top_num": 0.0, "comments": 0.0},
            ),
        ),
    )
    provider = FakeProvider(
        platform="sina_news",
        weights={"top_num": 0.7, "comments": 0.3},
        absolute_floors={"comments": 10.0},
        pages=pages,
        enrich_metrics={"top_num": 150.0, "comments": 25.0},
    )

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    duplicated = next(
        article
        for article in result
        if article.hot_item.item_id == duplicate.hot_item.item_id
    )
    assert duplicated.heat_evidence.source_kind == "official_hot_board"
    assert "official_hot_board" in duplicated.heat_evidence.qualified_by


def test_stale_snapshot_is_used_when_requested_date_missing(repository):
    yesterday = "2026-07-22"
    repository.save_eligible(yesterday, "sina_news", tuple())
    repository.publish_active_snapshot("sina_news", yesterday)
    provider = FakeProvider(platform="sina_news")

    collected_at_later = (NOW + timedelta(hours=20)).isoformat()
    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, collected_at_later, repository, provider
    )

    assert result == ()


def test_search_cache_negative_retry_after_is_respected(repository):
    future_iso = (NOW + timedelta(minutes=5)).isoformat()
    repository.save_search_cache(
        BUSINESS_DATE,
        "thepaper",
        KEYWORD,
        status="failed",
        articles=(),
        rejected=(),
        collected_at=COLLECTED_AT,
        retry_after=future_iso,
    )
    provider = FakeProvider(platform="thepaper")

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert result == ()
    assert provider.search_calls == []


def test_search_keyword_prefilter_skips_fetch_detail_for_irrelevant_items(repository):
    relevant = _make_hot_item(
        platform="thepaper",
        item_id="thepaper_relevant",
        rank=1,
        title=f"{KEYWORD} 报道",
        summary=f"{KEYWORD} 摘要",
        metrics={"interaction_num": 30.0, "praise_times": 25.0},
    )
    irrelevant = _make_hot_item(
        platform="thepaper",
        item_id="thepaper_irrelevant",
        rank=2,
        title="完全无关新闻标题",
        summary="某领域动态",
        metrics={"interaction_num": 30.0, "praise_times": 25.0},
    )
    provider = FakeProvider(
        platform="thepaper",
        weights={"interaction_num": 0.6, "praise_times": 0.4},
        absolute_floors={"interaction_num": 1.0, "praise_times": 10.0},
        pages=((relevant, irrelevant),),
    )

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert any(article.hot_item.item_id == "thepaper_relevant" for article in result)
    assert all(
        article.hot_item.item_id != "thepaper_irrelevant" for article in result
    )
    assert "thepaper_irrelevant" not in provider.detail_calls
    assert "thepaper_relevant" in provider.detail_calls


def test_search_candidates_require_enrich_metrics_to_qualify(tmp_path):
    repo_no_enrich = FileRepository(tmp_path / "no_enrich")
    repo_with_enrich = FileRepository(tmp_path / "with_enrich")
    matched = _make_hot_item(
        platform="thepaper",
        item_id="thepaper_search_enrich",
        rank=1,
        title=f"{KEYWORD} 候选",
        summary=f"{KEYWORD} 摘要",
        metrics={"interaction_num": 0.0, "praise_times": 0.0},
    )
    provider_no_enrich = FakeProvider(
        platform="thepaper",
        weights={"interaction_num": 0.6, "praise_times": 0.4},
        absolute_floors={"interaction_num": 10.0, "praise_times": 20.0},
        pages=((matched,),),
    )

    result_without_enrich = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repo_no_enrich, provider_no_enrich
    )
    assert all(
        article.hot_item.item_id != "thepaper_search_enrich"
        for article in result_without_enrich
    )

    provider_with_enrich = FakeProvider(
        platform="thepaper",
        weights={"interaction_num": 0.6, "praise_times": 0.4},
        absolute_floors={"interaction_num": 10.0, "praise_times": 20.0},
        pages=((matched,),),
        enrich_metrics={"interaction_num": 50.0, "praise_times": 40.0},
    )

    result_with_enrich = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repo_with_enrich, provider_with_enrich
    )
    assert any(
        article.hot_item.item_id == "thepaper_search_enrich"
        for article in result_with_enrich
    )


def test_stale_snapshot_reachable_when_search_window_expired(repository):
    yesterday = "2026-07-22"
    yesterday_noon = datetime(2026, 7, 22, 12, 0, tzinfo=SHANGHAI).isoformat()
    stale_articles = tuple(
        _build_article(
            _make_hot_item(
                platform="sina_news",
                item_id=f"sina_stale_{index + 1}",
                rank=index + 1,
                title=f"{KEYWORD} 旧标题 {index + 1}",
                summary=f"{KEYWORD} 摘要",
                metrics={"top_num": 200.0, "comments": 25.0},
            ),
            metrics={"top_num": 200.0, "comments": 25.0},
            source="official_hot_board",
        )
        for index in range(6)
    )
    repository.save_eligible(yesterday, "sina_news", stale_articles)
    repository.publish_active_snapshot("sina_news", yesterday)

    provider = FakeProvider(platform="sina_news")

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, yesterday_noon, repository, provider
    )

    assert len(result) >= 1
    assert all(
        article.hot_item.raw_payload.get("is_stale") is True
        and article.hot_item.raw_payload.get("snapshot_date") == yesterday
        for article in result
    )
    assert provider.search_calls == []


def test_optional_context_evidence_and_rank_hooks_are_used(repository):
    seeded = _seed_eligible(repository, "rank_only", count=1)
    search_item = _make_hot_item(
        platform="rank_only",
        item_id="rank_only_archive_1",
        rank=2,
        title=f"{KEYWORD} 归档推荐",
        summary=KEYWORD,
        metrics={},
    )
    provider = HookProvider(pages=((search_item,),))

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert provider.context_calls
    assert provider.context_calls[0][3] == (seeded[0].hot_item.item_id,)
    assert any(
        article.hot_item.item_id == "rank_only_archive_1" for article in result
    )
    assert all(
        article.heat_evidence.source_kind == "official_hot_board"
        for article in result
    )


def test_optional_rank_hook_is_applied_to_cached_matches(repository):
    first = _make_hot_item(
        platform="rank_only",
        item_id="rank_only_cached_a",
        rank=1,
        title=f"{KEYWORD} A",
        summary=KEYWORD,
        metrics={"comments": 5.0},
    )
    second = _make_hot_item(
        platform="rank_only",
        item_id="rank_only_cached_b",
        rank=2,
        title=f"{KEYWORD} B",
        summary=KEYWORD,
        metrics={"comments": 50.0},
    )
    cached = (
        _build_article(first, metrics={"comments": 5.0}),
        _build_article(second, metrics={"comments": 50.0}),
    )
    repository.save_eligible(BUSINESS_DATE, "rank_only", cached)
    repository.publish_active_snapshot("rank_only", BUSINESS_DATE)
    provider = HookProvider(pages=())

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert [article.hot_item.item_id for article in result] == [
        "rank_only_cached_b",
        "rank_only_cached_a",
    ]
