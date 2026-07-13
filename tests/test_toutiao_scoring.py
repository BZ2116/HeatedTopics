from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.toutiao_scoring import (
    DEFAULT_HOT_BOARD_RANK,
    HOT_BOARD_BASE_BOOST,
    IS_TOUTIAO_HOT_BOOST,
    PERSONA_MATCH_BOOST,
    SEARCH_BASE_OFFSET,
    as_sort_key,
    hybrid_score_v2,
)

import pytest


def _hot_board_item(hot_value: int, title: str = "Topic", rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"hb_{rank}",
        platform="toutiao",
        item_type="topic",
        title=title,
        url=f"https://www.toutiao.com/group/{rank}/",
        rank=rank,
        heat=HeatMetrics(
            value=hot_value, label=str(hot_value), metric_name="hot_value",
            metrics={"hot_value": hot_value},
        ),
        summary="",
        category="",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={"ClusterId": str(rank), "source_kind": "hot_board"},
    )


def _search_item(article_heat: int, title: str = "Search") -> HotItem:
    return HotItem(
        item_id="s_1",
        platform="toutiao",
        item_type="search_result",
        title=title,
        url="https://www.toutiao.com/group/999/",
        rank=1,
        heat=HeatMetrics(value=article_heat, label=str(article_heat), metric_name="article_heat", metrics={}),
        summary="",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={
            "source_kind": "article_info",
            "article_heat": article_heat,
            "is_toutiao_hot": False,
        },
    )


def test_hot_board_item_with_hot_value_1m_scores_above_search_with_article_heat_1k():
    import math

    hb = hybrid_score_v2(_hot_board_item(1_000_000))
    search = hybrid_score_v2(_search_item(1_000))
    # Hot board 1M -> log10(1_000_001) + 1.5 ≈ 7.5; search 1k -> log10(1001) + 3 ≈ 6.0
    assert hb.score > search.score
    assert math.isclose(hb.score, 7.5000, abs_tol=0.01)
    assert math.isclose(search.score, 6.0004, abs_tol=0.01)


def test_is_toutiao_hot_adds_half_point_to_search_item():
    base = hybrid_score_v2(_search_item(500))
    hot = hybrid_score_v2(
        HotItem(
            item_id="s_2",
            platform="toutiao",
            item_type="search_result",
            title="Search",
            url="https://www.toutiao.com/group/1000/",
            rank=1,
            heat=HeatMetrics(value=500, label="500", metric_name="article_heat", metrics={}),
            summary="",
            category="search",
            matched_query_ids=(),
            fetched_at="2026-07-13T08:00:00+08:00",
            fetch_status="success",
            raw_payload={
                "source_kind": "article_info",
                "article_heat": 500,
                "is_toutiao_hot": True,
            },
        )
    )
    assert hot.score - base.score == pytest.approx(IS_TOUTIAO_HOT_BOOST)
    assert hot.is_toutiao_hot is True


def test_persona_match_adds_three_tenths():
    item = _search_item(2000, title="AI写作工具评测")
    scored = hybrid_score_v2(item, persona_keywords=("AI写作",))
    assert scored.persona_matched is True
    base = hybrid_score_v2(_search_item(2000))
    assert scored.score - base.score == pytest.approx(PERSONA_MATCH_BOOST)


def test_persona_match_requires_keyword_in_searchable_text():
    item = _search_item(2000, title="Other Topic")
    scored = hybrid_score_v2(item, persona_keywords=("AI写作",))
    assert scored.persona_matched is False


def test_hot_board_rank_fallback_is_default():
    scored = hybrid_score_v2(_search_item(100))
    assert scored.hot_board_rank == DEFAULT_HOT_BOARD_RANK


def test_sort_key_orders_by_score_then_toutiao_hot_then_rank():
    a = hybrid_score_v2(_hot_board_item(2_000_000, rank=3))
    b = hybrid_score_v2(_hot_board_item(2_000_000, rank=1))
    c = hybrid_score_v2(_search_item(5000))
    candidates = [a, b, c]
    candidates.sort(key=as_sort_key)
    # same hot_value, rank 1 should outrank rank 3
    assert candidates[0].hot_board_rank == 1
    assert candidates[1].hot_board_rank == 3


def test_search_base_offset_brings_search_items_into_play():
    """A search item with article_heat=1000 should rank above any hot board item with HotValue < ~31."""
    item = _search_item(1000)
    scored = hybrid_score_v2(item)
    # log10(1001) + 3 ≈ 6.0
    assert scored.score > 5.5
    # hot board with hot_value=10 (way below 1M) should score lower
    tiny_hb = hybrid_score_v2(_hot_board_item(10))
    assert scored.score > tiny_hb.score