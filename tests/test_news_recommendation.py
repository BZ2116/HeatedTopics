"""Three-platform news recommendation bundle generation tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from heated_topics_v3.contracts import (
    ContentValidation,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    QualifiedArticle,
    UserProfile,
)
from heated_topics_v3.discovery import MAX_RESULTS
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.recommendation import generate_news_user_result
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
    user_id="u-news",
    primary_track="综合新闻",
    secondary_track="热榜",
    persona="news tester",
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
    metrics: Mapping[str, float] | None = None,
    publication_time: str | None = None,
) -> HotItem:
    return HotItem(
        item_id=item_id,
        platform=platform,
        title=title,
        url=f"https://example.test/{platform}/{item_id}",
        rank=rank,
        heat=_metrics(metrics),
        summary=summary,
        publication_time=publication_time,
        collected_at=COLLECTED_AT,
        raw_payload={},
    )


def _detail(item: HotItem) -> ItemDetail:
    return ItemDetail(
        item_id=item.item_id,
        content=_LONG_BODY,
        content_status="full_text",
        publication_time=item.publication_time,
        collected_at=COLLECTED_AT,
        source_url=item.url,
        fetch_status="success",
    )


def _evidence(item: HotItem, metrics: Mapping[str, float] | None = None) -> HeatEvidence:
    metrics_map = dict(metrics or {})
    if not metrics_map and item.heat.metrics:
        metrics_map = {k: float(v) for k, v in item.heat.metrics.items()}
    return HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=item.rank,
        native_hot_value=float(item.heat.value) if isinstance(item.heat.value, (int, float)) else None,
        metrics=metrics_map,
        threshold_metrics={},
        qualified_by=("official_hot_board",),
    )


def _build_article(item: HotItem, *, metrics: Mapping[str, float] | None = None) -> QualifiedArticle:
    validation = ContentValidation(
        status="accepted",
        parser="fixture",
        character_count=len(_LONG_BODY),
        paragraph_count=_LONG_BODY.count("\n\n") + 1,
        reasons=(),
    )
    return QualifiedArticle(
        hot_item=item,
        detail=_detail(item),
        heat_evidence=_evidence(item, metrics=metrics),
        content_validation=validation,
        platform_heat_score=0.0,
    )


class FakeNewsProvider:
    def __init__(
        self,
        platform: str,
        *,
        weights: Mapping[str, float] | None = None,
        absolute_floors: Mapping[str, float] | None = None,
        eligible: Sequence[QualifiedArticle] = (),
    ) -> None:
        self.platform = platform
        self.weights = dict(weights or {"comments": 0.5, "views": 0.5})
        self.absolute_floors = dict(absolute_floors or {"comments": 10.0})
        self._eligible = tuple(eligible)
        self.search_calls: list[tuple[str, int, int, str]] = []

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        return ProviderCapture(
            json.dumps({"platform": self.platform}), ".json", ()
        )

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        return _detail(item)

    def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        self.search_calls.append((keyword, page, page_size, collected_at))
        return ProviderCapture(
            json.dumps({"platform": self.platform, "page": page, "items": []}),
            ".json",
            (),
        )

    def enrich_metrics(
        self, items: Iterable[HotItem], collected_at: str
    ) -> tuple[HotItem, ...]:
        return tuple(items)


def _build_providers(
    *, counts: Mapping[str, int] | None = None
) -> dict[str, FakeNewsProvider]:
    counts = dict(counts or {})
    providers: dict[str, FakeNewsProvider] = {}
    for platform in ("sina_news", "thepaper", "netease_news", "baidu_hot", "zhihu_daily"):
        count = counts.get(platform, 3)
        if platform in ("baidu_hot", "zhihu_daily"):
            metrics_template: dict[str, float] = {"hot_score": 500.0}
        else:
            metrics_template = {"comments": 0.0, "views": 0.0}
        articles = []
        for index in range(count):
            metrics = (
                {"hot_score": 500.0}
                if platform in ("baidu_hot", "zhihu_daily")
                else {"comments": 20.0 + index, "views": 100.0 + index}
            )
            articles.append(
                _build_article(
                    _make_hot_item(
                        platform=platform,
                        item_id=f"{platform}_{index + 1}",
                        rank=index + 1,
                        title=f"{KEYWORD} {platform} {index + 1}",
                        summary=f"{KEYWORD} 摘要",
                        metrics=metrics,
                    ),
                    metrics=metrics,
                )
            )
        articles = tuple(articles)
        if platform in ("baidu_hot", "zhihu_daily"):
            weights = {"hot_score": 1.0}
            floors = {"hot_score": 1.0}
        else:
            weights = {"comments": 0.5, "views": 0.5}
            floors = {"comments": 10.0}
        providers[platform] = FakeNewsProvider(
            platform=platform,
            weights=weights,
            absolute_floors=floors,
            eligible=articles,
        )
    return providers


def _seed_eligible(
    repository: FileRepository, platform: str, articles: Sequence[QualifiedArticle]
) -> None:
    repository.save_eligible(BUSINESS_DATE, platform, articles)
    repository.publish_active_snapshot(platform, BUSINESS_DATE)


def test_news_generation_returns_each_platform_independently(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 7, "thepaper": 4, "netease_news": 12})
    for platform, provider in providers.items():
        _seed_eligible(repository, platform, provider._eligible)

    bundle = generate_news_user_result(PROFILE, NOW, repository, providers)

    assert bundle.status == "generated"
    assert bundle.user_id == PROFILE.user_id
    assert bundle.business_date == BUSINESS_DATE
    metadata = bundle.query_metadata["platforms"]
    assert metadata["sina_news"]["count"] <= 20
    assert metadata["thepaper"]["count"] <= 20
    assert metadata["netease_news"]["count"] <= 20
    assert all(
        item.content_status == "full_text" for item in bundle.recommendations
    )
    assert bundle.potential_topics == ()
    assert bundle.general_fallback == ()


def test_news_generation_uses_only_full_text_qualified_articles(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 6, "thepaper": 6, "netease_news": 6})
    for platform, provider in providers.items():
        _seed_eligible(repository, platform, provider._eligible)

    bundle = generate_news_user_result(PROFILE, NOW, repository, providers)

    for item in bundle.recommendations:
        assert item.content_status == "full_text"
        evidence = item.evidence
        assert evidence["qualified_by"]
        assert evidence["metrics"]
        assert evidence["source_kind"] == "official_hot_board"
        assert "platform_heat_score" in evidence


def test_news_generation_isolates_results_to_news_user_dir(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 6, "thepaper": 6, "netease_news": 6})
    for platform, provider in providers.items():
        _seed_eligible(repository, platform, provider._eligible)

    bundle = generate_news_user_result(PROFILE, NOW, repository, providers)

    result_dir = tmp_path / "news_user_results" / PROFILE.user_id / BUSINESS_DATE
    assert (result_dir / "result.json").is_file()
    assert (result_dir / "report.md").is_file()
    assert not (tmp_path / "user_results").exists()
    assert result_dir == (
        tmp_path / "news_user_results" / PROFILE.user_id / BUSINESS_DATE
    )


def test_news_generation_reuses_same_day_result_without_search(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 6, "thepaper": 4, "netease_news": 4})
    for platform, provider in providers.items():
        _seed_eligible(repository, platform, provider._eligible)

    first = generate_news_user_result(PROFILE, NOW, repository, providers)
    search_after_first = {
        platform: len(provider.search_calls) for platform, provider in providers.items()
    }

    second = generate_news_user_result(PROFILE, NOW, repository, providers)

    assert first.status in {"generated", "no_result"}
    assert second.status == "existing"
    assert second.business_date == first.business_date
    for platform, provider in providers.items():
        assert len(provider.search_calls) - search_after_first[platform] == 0


def test_news_generation_returns_no_result_when_all_platforms_empty(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 0, "thepaper": 0, "netease_news": 0})

    bundle = generate_news_user_result(PROFILE, NOW, repository, providers)

    assert bundle.status == "no_result"
    assert bundle.recommendations == ()
    assert bundle.potential_topics == ()
    assert bundle.general_fallback == ()


def test_news_generation_returns_failed_when_repository_missing(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 0, "thepaper": 0, "netease_news": 0})

    bundle = generate_news_user_result(PROFILE, NOW, repository, providers)

    assert bundle.status in {"no_result", "failed"}


def test_news_generation_preserves_heat_evidence_metrics(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers(counts={"sina_news": 6, "thepaper": 6, "netease_news": 6})
    for platform, provider in providers.items():
        _seed_eligible(repository, platform, provider._eligible)

    bundle = generate_news_user_result(PROFILE, NOW, repository, providers)

    for item in bundle.recommendations:
        evidence = item.evidence
        assert "metrics" in evidence
        assert "qualified_by" in evidence
        assert evidence["source_kind"] == "official_hot_board"
        assert evidence["platform_heat_score"] >= 0.0

def test_news_recommendation_uses_supporting_article_source_url(tmp_path):
    from heated_topics_v3.recommendation import _article_to_recommendation

    repository = FileRepository(tmp_path)
    item = _make_hot_item(
        platform="baidu_hot",
        item_id="baidu_hot_support",
        rank=1,
        title=f"{KEYWORD} 人工智能手机发布",
        summary="百度热搜事件",
        metrics={"hot_score": 987654.0},
    )
    evidence = HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=1,
        native_hot_value=987654.0,
        metrics={"hot_score": 987654.0},
        threshold_metrics={"hot_score": 1.0},
        qualified_by=("official_hot_board",),
    )
    detail = ItemDetail(
        item.item_id,
        _LONG_BODY,
        "full_text",
        None,
        BUSINESS_DATE + "T08:01:00+08:00",
        "https://news.example.test/article",
        "success",
    )
    validation = ContentValidation("accepted", "article", 500, 4, ())
    article = QualifiedArticle(item, detail, evidence, validation, 0.0)
    recommendation = _article_to_recommendation(article)
    assert recommendation.source_url == "https://news.example.test/article"
    assert recommendation.platform == "baidu_hot"


def test_news_recommendation_platforms_constant_lists_all_six():
    from heated_topics_v3.recommendation import NEWS_DISPLAY_ORDER

    assert NEWS_DISPLAY_ORDER == (
        "sina_news",
        "thepaper",
        "netease_news",
        "baidu_hot",
        "zhihu_hot",
        "zhihu_daily",
    )
