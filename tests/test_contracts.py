from typing import get_args

from heated_topics_v3.contracts import (
    ContentStatus,
    DailySnapshot,
    FactStatus,
    GenerationStatus,
    HeatLevel,
    HeatMetrics,
    HotItem,
    ItemDetail,
    PlatformCollectionStatus,
    RecommendationBundle,
    RecommendationItem,
    UserProfile,
)


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


def test_workflow_status_literals_are_exact():
    assert get_args(HeatLevel) == (1, 2, 3)
    assert get_args(FactStatus) == ("verified", "unverified", "disputed", "debunked")
    assert get_args(ContentStatus) == ("full_text", "summary", "title_only")
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
