"""Dynamic heat floors and stable per-platform ranking."""

from __future__ import annotations

import pytest

from heated_topics_v3.contracts import (
    ContentValidation,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    QualifiedArticle,
)


def _qualified(
    *,
    item_id: str,
    rank: int | None,
    source_kind: str,
    metrics: dict[str, float],
    publication_time: str | None = "2026-07-23T10:00:00+08:00",
) -> QualifiedArticle:
    evidence = HeatEvidence(
        source_kind=source_kind,  # type: ignore[arg-type]
        platform_rank=rank,
        native_hot_value=metrics.get("views") if metrics else None,
        metrics=metrics,
        qualified_by=("official_hot_board",) if source_kind == "official_hot_board" else tuple(metrics.keys()),
    )
    hot_item = HotItem(
        item_id=item_id,
        platform="sina_news",
        title=f"title-{item_id}",
        url=f"https://example.com/{item_id}",
        rank=rank,
        heat=HeatMetrics(value=None, label="", metric_name=source_kind),
        summary=f"summary-{item_id}",
        publication_time=publication_time,
        collected_at="2026-07-23T00:00:00+08:00",
    )
    detail = ItemDetail(
        item_id=item_id,
        content=("段落一。\n\n段落二。\n\n段落三。" * 5),
        content_status="full_text",
        publication_time=publication_time,
        collected_at="2026-07-23T00:00:00+08:00",
        source_url=f"https://example.com/{item_id}",
        fetch_status="success",
    )
    validation = ContentValidation(
        status="accepted", parser="fixture", character_count=300, paragraph_count=3, reasons=()
    )
    return QualifiedArticle(
        hot_item=hot_item,
        detail=detail,
        heat_evidence=evidence,
        content_validation=validation,
        platform_heat_score=0.0,
    )


@pytest.fixture
def qualified_articles() -> tuple[QualifiedArticle, ...]:
    high = _qualified(
        item_id="high",
        rank=1,
        source_kind="official_hot_board",
        metrics={
            "views": 1000.0,
            "comments": 500.0,
            "likes": 200.0,
            "shares": 80.0,
            "collects": 30.0,
        },
    )
    medium = _qualified(
        item_id="medium",
        rank=10,
        source_kind="official_hot_board",
        metrics={
            "views": 100.0,
            "comments": 50.0,
            "likes": 20.0,
            "shares": 8.0,
            "collects": 3.0,
        },
    )
    low = _qualified(
        item_id="low",
        rank=None,
        source_kind="public_engagement",
        # views intentionally omitted to prove missing metrics contribute zero
        metrics={
            "comments": 10.0,
            "likes": 5.0,
            "shares": 2.0,
            "collects": 1.0,
        },
    )
    return (high, medium, low)


def test_positive_percentile_ignores_zero_and_uses_absolute_fallback() -> None:
    from heated_topics_v3.heat import (
        dynamic_floors,
        positive_percentile,
    )

    assert positive_percentile([0, 10, 20, 30, 40], 0.25) == 17.5
    assert dynamic_floors(
        [{"comments": 0}, {"comments": 0}],
        {"comments": 10},
    ) == {"comments": 10.0}


def test_public_metrics_require_at_least_one_comparable_floor() -> None:
    from heated_topics_v3.heat import qualifies_public_metrics

    floors = {"comments": 20.0, "likes": 50.0}
    assert qualifies_public_metrics({"comments": 21.0}, floors) == ("comments",)
    assert qualifies_public_metrics({"comments": 19.0, "views": 999.0}, floors) == ()


def test_ranking_uses_percentiles_missing_zero_and_stable_ties(
    qualified_articles: tuple[QualifiedArticle, ...],
) -> None:
    from heated_topics_v3.heat import rank_platform_articles

    weights = {
        "views": 0.45,
        "comments": 0.25,
        "likes": 0.20,
        "shares": 0.07,
        "collects": 0.03,
    }
    ranked = rank_platform_articles(qualified_articles, weights)
    assert [item.hot_item.item_id for item in ranked] == ["high", "medium", "low"]
    assert ranked[0].platform_heat_score > ranked[1].platform_heat_score
    assert ranked[1].platform_heat_score > ranked[2].platform_heat_score
