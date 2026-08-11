from typing import get_args

import pytest

from heated_topics_v3.contracts import (
    ContentValidation,
    ContentStatus,
    DailySnapshot,
    FactStatus,
    GenerationStatus,
    HeatEvidence,
    HeatLevel,
    HeatMetrics,
    HotItem,
    ItemDetail,
    PlatformCollectionStatus,
    QualifiedArticle,
    RecommendationBundle,
    RecommendationItem,
    UserProfile,
)


@pytest.fixture
def hot_item():
    return HotItem(
        item_id="baidu_1",
        platform="baidu",
        title="事件标题",
        url="https://example.com/topic",
        rank=1,
        heat=HeatMetrics(value=100, label="100", metric_name="hot_index"),
        summary="事件摘要",
        publication_time=None,
        collected_at="2026-07-13T08:00:00+08:00",
    )


@pytest.fixture
def item_detail():
    return ItemDetail(
        item_id="baidu_1",
        content="完整正文",
        content_status="full_text",
        publication_time=None,
        collected_at="2026-07-13T08:00:00+08:00",
        source_url="https://example.com/topic",
        fetch_status="success",
    )


def test_qualified_article_requires_full_text_and_verified_evidence(hot_item, item_detail):
    evidence = HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=1,
        native_hot_value=100.0,
        metrics={"views": 100.0},
        threshold_metrics={},
        qualified_by=("official_hot_board",),
    )
    article = QualifiedArticle(
        hot_item=hot_item,
        detail=item_detail,
        heat_evidence=evidence,
        content_validation=ContentValidation("accepted", "fixture", 300, 3, ()),
        platform_heat_score=0.0,
    )
    assert article.detail.content_status == "full_text"


@pytest.mark.parametrize(
    ("qualified_by", "platform_rank", "native_hot_value"),
    [
        (("rank",), 1, None),
        (("official_hot_board",), None, None),
        (("official_hot_board",), 0, 0.0),
    ],
)
def test_official_heat_evidence_requires_source_marker_and_positive_native_signal(
    qualified_by, platform_rank, native_hot_value
):
    with pytest.raises(ValueError, match="official hot board evidence"):
        HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=platform_rank,
            native_hot_value=native_hot_value,
            qualified_by=qualified_by,
        )


@pytest.mark.parametrize(
    ("metrics", "qualified_by"),
    [
        ({"views": 100.0}, ("public_engagement",)),
        ({"views": 0.0}, ("views",)),
        ({}, ("views",)),
    ],
)
def test_public_heat_evidence_requires_named_positive_metric(metrics, qualified_by):
    with pytest.raises(ValueError, match="public engagement evidence"):
        HeatEvidence(
            source_kind="public_engagement",
            platform_rank=None,
            native_hot_value=None,
            metrics=metrics,
            qualified_by=qualified_by,
        )


def test_public_heat_evidence_accepts_named_positive_metric():
    evidence = HeatEvidence(
        source_kind="public_engagement",
        platform_rank=None,
        native_hot_value=None,
        metrics={"views": 100.0, "comments": 0.0},
        qualified_by=("views",),
    )
    assert evidence.qualified_by == ("views",)


def test_user_profile_stores_primary_keyword():
    profile = UserProfile(
        user_id="u1",
        primary_track="人工智能",
        secondary_track="AI应用",
        persona="职场工具测评",
        primary_keyword="AI工具",
        updated_at="2026-07-13T08:00:00+08:00",
    )
    assert profile.primary_keyword == "AI工具"


def test_recommendation_keeps_heat_and_fact_status():
    item = RecommendationItem(
        hot_item_id="baidu_1",
        platform="baidu",
        title="测试热点",
        heat_level=1,
        fact_status="unverified",
        publication_time=None,
        collected_at="2026-07-13T08:00:00+08:00",
        detail="热点解释",
        content_status="summary",
        is_personalized=True,
        evidence={"rank": 1, "hot_index": 100},
    )
    assert item.heat_level == 1
    assert item.fact_status == "unverified"


def test_item_detail_accepts_each_content_status():
    for status in ("full_text", "summary", "title_only"):
        detail = ItemDetail(
            item_id="baidu_1",
            content="content",
            content_status=status,
            publication_time=None,
            collected_at="2026-07-13T08:00:00+08:00",
            source_url="https://example.com/topic",
            fetch_status="success",
        )
        assert detail.content_status == status


def test_item_detail_metadata_defaults_empty_and_is_immutable_contract():
    from heated_topics_v3.contracts import ItemDetail

    detail = ItemDetail(
        item_id="zhihu_hot_question_1",
        content="第一段完整正文。\n\n第二段完整正文。",
        content_status="full_text",
        publication_time=None,
        collected_at="2026-07-25T08:00:00+08:00",
        source_url="https://www.zhihu.com/question/1",
        fetch_status="success",
    )
    assert detail.metadata == {}


def test_workflow_status_literals_are_exact():
    assert get_args(HeatLevel) == (1, 2, 3)
    assert get_args(FactStatus) == ("verified", "unverified", "disputed", "debunked")
    assert get_args(ContentStatus) == (
        "full_text",
        "summary",
        "title_only",
        "rejected",
    )
    assert get_args(GenerationStatus) == (
        "existing",
        "generated",
        "no_result",
        "not_ready",
        "failed",
    )


def test_daily_snapshot_groups_immutable_platform_items():
    item = HotItem(
        item_id="baidu_1",
        platform="baidu",
        title="topic",
        url="https://example.com/topic",
        rank=1,
        heat=HeatMetrics(value=100, label="100", metric_name="hot_index"),
        summary="summary",
        publication_time=None,
        collected_at="2026-07-13T08:00:00+08:00",
        raw_payload={"word": "topic"},
    )
    status = PlatformCollectionStatus(
        platform="baidu", status="success", collected_at=item.collected_at, item_count=1
    )
    snapshot = DailySnapshot(
        business_date="2026-07-13",
        collected_at=item.collected_at,
        items_by_platform={"baidu": (item,)},
        platform_statuses=(status,),
    )
    assert snapshot.items_by_platform["baidu"] == (item,)


def test_recommendation_bundle_keeps_all_output_sections():
    bundle = RecommendationBundle(
        status="generated",
        user_id="u1",
        business_date="2026-07-13",
        generated_at="2026-07-13T08:00:00+08:00",
        recommendations=(),
        potential_topics=(),
        general_fallback=(),
        query_metadata={"primary_keyword": "AI工具"},
    )
    assert bundle.query_metadata["primary_keyword"] == "AI工具"
