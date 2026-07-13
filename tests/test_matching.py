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


def test_overlap_checks_all_board_group_ids_before_title_fallback():
    title_fallback = item(
        "toutiao_title",
        "toutiao",
        "AI工具 发布",
        rank=1,
        heat_value=100,
        raw_payload={"ClusterIdStr": "wrong"},
    )
    group_id_match = item(
        "toutiao_group",
        "toutiao",
        "另一榜单标题",
        rank=2,
        heat_value=200,
        raw_payload={"ClusterIdStr": "strong"},
    )
    search_item = item(
        "toutiao_search",
        "toutiao",
        "ＡＩ工具\u3000发布",
        metric_name="search_rank",
        raw_payload={"group_id": "strong"},
    )

    merged = merge_toutiao_results((title_fallback, group_id_match), (search_item,))
    merged_search = next(record for record in merged if record.item_id == "toutiao_search")

    assert merged_search.rank == 2
    assert merged_search.heat == group_id_match.heat
    assert merged_search.raw_payload["v1_evidence"]["board_item_id"] == "toutiao_group"
    assert merged_search.raw_payload["v1_evidence"]["overlap_method"] == "group_id"


@pytest.mark.parametrize(
    ("overlap_method", "board_url", "search_url", "board_title", "search_title"),
    [
        (
            "canonical_url",
            "https://www.toutiao.com/group/900/",
            "https://toutiao.com/group/900/?from=search",
            "普通榜单标题",
            "普通搜索标题",
        ),
        (
            "normalized_title",
            "https://example.com/board/",
            "https://example.com/search/",
            "普通 ＡＩ 主题",
            "普通 ai 主题",
        ),
    ],
)
def test_url_or_title_overlap_can_use_official_detail_with_different_item_id(
    overlap_method: str,
    board_url: str,
    search_url: str,
    board_title: str,
    search_title: str,
):
    board_item = item(
        "toutiao_board",
        "toutiao",
        board_title,
        url=board_url,
        raw_payload={"ClusterIdStr": "board-id"},
    )
    search_item = item(
        "toutiao_search",
        "toutiao",
        search_title,
        url=search_url,
        metric_name="search_rank",
        raw_payload={"group_id": "search-id"},
    )
    official_detail = detail(board_item, "官方正文只在这里提到 AI工具")

    recommendations = build_v1_recommendations(
        profile(),
        (board_item,),
        (search_item,),
        (),
        {board_item.item_id: official_detail},
    )

    assert [record.hot_item_id for record in recommendations] == ["toutiao_search"]
    assert recommendations[0].detail == official_detail.content
    assert recommendations[0].content_status == official_detail.content_status
    assert recommendations[0].evidence["overlap_method"] == overlap_method


def test_empty_urls_are_skipped_during_overlap_matching():
    board_item = replace(
        item("toutiao_board", "toutiao", "榜单标题", raw_payload={"ClusterIdStr": "1"}),
        url="",
    )
    search_item = replace(
        item(
            "toutiao_search",
            "toutiao",
            "不同搜索标题",
            metric_name="search_rank",
            raw_payload={"group_id": "2"},
        ),
        url="",
    )

    merged = merge_toutiao_results((board_item,), (search_item,))
    merged_search = next(record for record in merged if record.item_id == "toutiao_search")

    assert len(merged) == 2
    assert merged_search.raw_payload["v1_evidence"]["source_kind"] == "keyword_search"


@pytest.mark.parametrize(
    ("summary", "expected_content", "expected_status"),
    [
        ("AI工具 摘要", "AI工具 摘要", "summary"),
        ("", "AI工具 标题", "title_only"),
    ],
)
def test_empty_detail_content_falls_back_to_summary_then_title(
    summary: str, expected_content: str, expected_status: str
):
    juejin_item = item("juejin_1", "juejin", "AI工具 标题", summary=summary)
    empty_detail = detail(juejin_item, "")

    recommendations = build_v1_recommendations(
        profile(), (), (), (juejin_item,), {juejin_item.item_id: empty_detail}
    )

    assert recommendations[0].detail == expected_content
    assert recommendations[0].content_status == expected_status
