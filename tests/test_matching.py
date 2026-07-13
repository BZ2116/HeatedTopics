from dataclasses import replace

import pytest

from heated_topics_v3.contracts import (
    HeatMetrics,
    HotItem,
    ItemDetail,
    UserProfile,
)
from heated_topics_v3.matching import (
    TOUTIAO_UNVERIFIED_NOTICE,
    build_v1_recommendations,
    matches_primary_keyword,
    merge_toutiao_results,
)


NOW = "2026-07-13T04:00:00Z"


def profile(keyword: str = "ＡＩ工具") -> UserProfile:
    return UserProfile("u1", "AI", "应用", "职场", keyword, NOW)


def item(
    item_id: str,
    platform: str,
    title: str,
    *,
    summary: str = "",
    url: str | None = None,
    rank: int = 1,
    metric_name: str | None = None,
    heat_value: int | None = None,
    raw_payload: dict | None = None,
) -> HotItem:
    if metric_name is None:
        metric_name = "hot_value" if platform == "toutiao" else "hot_rank"
    if heat_value is None:
        heat_value = rank
    return HotItem(
        item_id=item_id,
        platform=platform,
        title=title,
        url=url or f"https://example.com/{item_id}/",
        rank=rank,
        heat=HeatMetrics(
            heat_value,
            str(heat_value),
            metric_name,
            {metric_name: heat_value},
        ),
        summary=summary,
        publication_time=None,
        collected_at=NOW,
        raw_payload=raw_payload or {},
    )


def detail(hot_item: HotItem, content: str) -> ItemDetail:
    return ItemDetail(
        hot_item.item_id,
        content,
        "full_text",
        hot_item.publication_time,
        NOW,
        hot_item.url,
        "success",
    )


@pytest.mark.parametrize("field", ["title", "summary", "detail"])
def test_keyword_matching_normalizes_unicode_across_all_text_fields(field: str):
    hot_item = item("juejin_1", "juejin", "普通标题", summary="普通摘要")
    item_detail = detail(hot_item, "普通正文")
    normalized_match = "适合职场的ai工具"
    if field == "title":
        hot_item = replace(hot_item, title=normalized_match)
    elif field == "summary":
        hot_item = replace(hot_item, summary=normalized_match)
    else:
        item_detail = detail(hot_item, normalized_match)

    assert matches_primary_keyword(profile(), hot_item, item_detail)


def test_keyword_matching_does_not_expand_aliases_or_use_other_profile_fields():
    hot_item = item("juejin_1", "juejin", "人工智能应用")

    assert not matches_primary_keyword(profile("AI工具"), hot_item)


@pytest.mark.parametrize(
    ("board_values", "search_values", "expected_method"),
    [
        (
            {"raw_payload": {"ClusterIdStr": "101"}},
            {"raw_payload": {"group_id": "101"}},
            "group_id",
        ),
        (
            {"url": "https://www.toutiao.com/group/202/?from=hot#top"},
            {"url": "http://toutiao.com/group/202"},
            "canonical_url",
        ),
        (
            {"title": "ＡＩ  Agent\u3000发布"},
            {"title": "ai agent 发布"},
            "normalized_title",
        ),
    ],
)
def test_toutiao_overlap_uses_ordered_identity_fallbacks(
    board_values: dict, search_values: dict, expected_method: str
):
    board_item = replace(
        item("toutiao_board", "toutiao", "榜单标题", rank=7, heat_value=98765),
        **board_values,
    )
    search_item = replace(
        item(
            "toutiao_search",
            "toutiao",
            "搜索标题",
            rank=1,
            metric_name="search_rank",
            heat_value=1,
        ),
        **search_values,
    )

    merged = merge_toutiao_results((board_item,), (search_item,))

    assert len(merged) == 1
    assert merged[0].item_id == search_item.item_id
    assert merged[0].rank == 7
    assert merged[0].heat == board_item.heat
    assert merged[0].raw_payload["v1_evidence"]["overlap_method"] == expected_method


def test_nonoverlap_stays_search_rank_and_carries_exact_notice():
    search_item = item(
        "toutiao_search",
        "toutiao",
        "AI工具搜索结果",
        metric_name="search_rank",
        heat_value=1,
    )

    merged = merge_toutiao_results((), (search_item,))
    recommendations = build_v1_recommendations(profile(), (), merged, (), {})

    assert merged[0].heat.metric_name == "search_rank"
    assert recommendations[0].heat_level == 3
    assert recommendations[0].evidence["notice"] == TOUTIAO_UNVERIFIED_NOTICE
    assert TOUTIAO_UNVERIFIED_NOTICE == "来自头条关键词搜索，未发现官方热榜证据"


def test_build_preserves_platform_and_source_order_without_cross_platform_deduplication():
    toutiao_second = item("toutiao_2", "toutiao", "AI工具 同一事件", rank=2, heat_value=200)
    toutiao_first = item("toutiao_1", "toutiao", "AI工具 第一条", rank=1, heat_value=300)
    toutiao_search = item(
        "toutiao_s1",
        "toutiao",
        "AI工具 搜索候选",
        rank=1,
        metric_name="search_rank",
        heat_value=1,
    )
    juejin_second = item("juejin_2", "juejin", "AI工具 第二条", rank=2, heat_value=20)
    juejin_duplicate = item("juejin_1", "juejin", "AI工具 同一事件", rank=1, heat_value=30)

    recommendations = build_v1_recommendations(
        profile(),
        (toutiao_first, toutiao_second),
        (toutiao_search,),
        (juejin_duplicate, juejin_second),
        {},
    )

    assert [record.hot_item_id for record in recommendations] == [
        "toutiao_1",
        "toutiao_2",
        "toutiao_s1",
        "juejin_1",
        "juejin_2",
    ]
    assert [record.heat_level for record in recommendations] == [1, 1, 3, 1, 1]
    assert [record.platform for record in recommendations] == [
        "toutiao",
        "toutiao",
        "toutiao",
        "juejin",
        "juejin",
    ]
    assert sum(record.title == "AI工具 同一事件" for record in recommendations) == 2


def test_build_uses_detail_for_matching_and_recommendation_content():
    juejin_item = item("juejin_1", "juejin", "普通标题", summary="普通摘要")
    item_detail = detail(juejin_item, "正文介绍 AI工具")

    recommendations = build_v1_recommendations(
        profile(), (), (), (juejin_item,), {juejin_item.item_id: item_detail}
    )

    assert recommendations[0].detail == item_detail.content
    assert recommendations[0].content_status == "full_text"
    assert recommendations[0].heat_level == 1
