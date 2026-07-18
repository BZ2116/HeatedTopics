from heated_topics_v3.contracts import ExtractedKeyword, HeatMetrics, HotItem
from heated_topics_v3.toutiao_paths import (
    PATH_A,
    PATH_B,
    PATH_C,
    Candidate,
    HeatSelection,
    PathFilters,
    build_candidates,
    select_search_candidates_by_heat,
)


def _hb(cluster_id: str, hot_value: int, title: str, rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"hb_{cluster_id}",
        platform="toutiao",
        item_type="topic",
        title=title,
        url=f"https://www.toutiao.com/group/{cluster_id}/",
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
        raw_payload={"ClusterId": cluster_id, "source_kind": "hot_board"},
    )


def _search(article_id: str, title: str, article_heat: int, is_toutiao_hot: bool = False) -> HotItem:
    return _search_with_url(
        f"https://www.toutiao.com/group/{article_id}/",
        title, article_heat, is_toutiao_hot,
    )


def _search_with_url(
    url: str, title: str, article_heat: int, is_toutiao_hot: bool = False,
) -> HotItem:
    return HotItem(
        item_id=f"search_{title}",
        platform="toutiao",
        item_type="search_result",
        title=title,
        url=url,
        rank=1,
        heat=HeatMetrics(
            value=article_heat, label=str(article_heat), metric_name="article_heat", metrics={},
        ),
        summary="",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={
            "source_kind": "article_info",
            "search_phrase": "AI写作",
            "article_heat": article_heat,
        },
    )


def _info(article_heat: int, is_toutiao_hot: bool = False) -> dict:
    return {
        "impression_count": 100,
        "digg_count": 10,
        "comment_count": 5,
        "repost_count": 0,
        "repin_count": 1,
        "is_toutiao_hot": is_toutiao_hot,
        "article_heat": article_heat,
    }


def test_path_a_keeps_hot_board_above_1m_with_persona_match():
    hot_board = [
        _hb("1", 2_000_000, "AI写作工具爆发", rank=1),
        _hb("2", 50_000, "Other", rank=2),  # below 1M
    ]
    candidates = build_candidates(
        hot_board=hot_board,
        persona_keywords=("AI写作",),
        filters=PathFilters(hot_board_min=1_000_000),
    )
    paths = [c.source_path for c in candidates]
    assert PATH_A in paths
    titles = [c.item.title for c in candidates]
    assert "AI写作工具爆发" in titles
    assert "Other" not in titles


def test_path_b_includes_search_items_above_article_heat_1k():
    candidates = build_candidates(
        hot_board=[],
        keywords=(ExtractedKeyword("AI写作", "热榜"),),
        persona_keywords=("AI写作",),
        search_results_by_keyword={
            "AI写作": [
                _search("100", "AI写作利器", article_heat=1500),
                _search("200", "弱搜索", article_heat=100),
            ],
        },
        article_info_by_url={
            "https://www.toutiao.com/group/100/": _info(1500),
            "https://www.toutiao.com/group/200/": _info(100),
        },
        filters=PathFilters(article_heat_min=1_000),
    )
    titles = [c.item.title for c in candidates]
    assert "AI写作利器" in titles
    assert "弱搜索" not in titles


def test_path_c_retrieves_is_toutiao_hot_below_500():
    candidates = build_candidates(
        hot_board=[],
        keywords=(ExtractedKeyword("AI写作", "兜底"),),
        search_results_by_keyword={
            "AI写作": [
                _search("300", "低热但Toutiao标记", article_heat=200),
            ],
        },
        article_info_by_url={
            "https://www.toutiao.com/group/300/": _info(200, is_toutiao_hot=True),
        },
        filters=PathFilters(
            article_heat_min=1_000,
            is_toutiao_hot_min_article_heat=0,
            is_toutiao_hot_max_article_heat=500,
        ),
    )
    assert len(candidates) == 1
    assert candidates[0].source_path == PATH_C
    assert candidates[0].is_toutiao_hot is True


def test_paths_dedupe_by_canonical_url_with_merged_source_path():
    same_url = "https://www.toutiao.com/group/500/"
    hot_board = [
        HotItem(
            item_id="hb_500",
            platform="toutiao",
            item_type="topic",
            title="AI写作工具霸榜",
            url=same_url,
            rank=1,
            heat=HeatMetrics(value=3_000_000, label="3000000", metric_name="hot_value", metrics={"hot_value": 3000000}),
            summary="",
            category="",
            matched_query_ids=(),
            fetched_at="2026-07-13T08:00:00+08:00",
            fetch_status="success",
            raw_payload={"ClusterId": "500", "source_kind": "hot_board"},
        ),
    ]
    candidates = build_candidates(
        hot_board=hot_board,
        keywords=(ExtractedKeyword("AI写作", "热榜"),),
        persona_keywords=("AI写作",),
        search_results_by_keyword={
            "AI写作": [_search("500", "Search Dup", article_heat=2000)],
        },
        article_info_by_url={same_url: _info(2000)},
        filters=PathFilters(hot_board_min=1_000_000, article_heat_min=1_000),
    )
    assert len(candidates) == 1
    assert "+" in candidates[0].source_path
    assert PATH_A in candidates[0].source_path
    assert PATH_B in candidates[0].source_path


def test_paths_keep_distinct_jump_url_articles_as_separate_candidates():
    """Search results with /search/jump wrappers hide the article_id in h5_url.

    When every item canonicalizes to `/search/jump` the dedup must NOT collapse
    them — distinct articles must remain distinct candidates.
    """
    def _jump(article_id: str) -> str:
        return (
            f"/search/jump?aid=1455&jtoken=TOKEN&url=https%3A%2F%2Farticle.zlink.toutiao.com"
            f"%2Fabcd%3Fh5_url%3Dhttps%253A%252F%252Ftoutiao.com%252Fgroup%252F{article_id}%252F"
        )

    items = [
        _search_with_url(_jump("111"), "第一篇", article_heat=5000),
        _search_with_url(_jump("222"), "第二篇", article_heat=3000),
        _search_with_url(_jump("333"), "第三篇", article_heat=1500),
    ]
    candidates = build_candidates(
        hot_board=[],
        keywords=(ExtractedKeyword("校招", "热榜"),),
        persona_keywords=("校招",),
        search_results_by_keyword={"校招": items},
        article_info_by_url={},  # dedup key now independent of article_info dict
        filters=PathFilters(article_heat_min=0),
    )
    titles = sorted(c.item.title for c in candidates)
    assert titles == ["第一篇", "第三篇", "第二篇"]
    assert all(c.source_path == PATH_B for c in candidates)


def test_paths_dedupe_jump_url_for_same_article_across_keywords():
    """Same article from two different keyword searches should dedup to 1."""
    def _jump(article_id: str) -> str:
        return (
            f"/search/jump?aid=1455&jtoken=TOKEN&url=https%3A%2F%2Farticle.zlink.toutiao.com"
            f"%2Fabcd%3Fh5_url%3Dhttps%253A%252F%252Ftoutiao.com%252Fgroup%252F{article_id}%252F"
        )

    same_article = _search_with_url(_jump("999"), "同篇文章", article_heat=2000)
    candidates = build_candidates(
        hot_board=[],
        keywords=(
            ExtractedKeyword("校招", "热榜"),
            ExtractedKeyword("秋招", "热榜"),
        ),
        persona_keywords=("校招", "秋招"),
        search_results_by_keyword={
            "校招": [same_article],
            "秋招": [same_article],
        },
        article_info_by_url={},
        filters=PathFilters(article_heat_min=0),
    )
    assert len(candidates) == 1
    # Both keyword paths dedupe to a single B (set-based merge).
    assert candidates[0].source_path == PATH_B
    # matched_keyword is whichever scored higher (or first inserted).
    assert candidates[0].matched_keyword in {"校招", "秋招"}


# ---------------------------------------------------------------------------
# select_search_candidates_by_heat (adaptive top-N)
# ---------------------------------------------------------------------------


def _search_candidate(article_id: str, article_heat: int, is_toutiao_hot: bool = False) -> Candidate:
    return Candidate(
        item=_search(article_id, f"Article {article_id}", article_heat=article_heat, is_toutiao_hot=is_toutiao_hot),
        source_path=PATH_B,
        matched_keyword="AI写作",
        is_toutiao_hot=is_toutiao_hot,
        is_hot_board=False,
        preliminary_score=article_heat / 1000.0,
    )


def test_select_search_candidates_keeps_only_high_heat_when_5_or_more_qualify():
    candidates = [
        _search_candidate("1", 30_000),
        _search_candidate("2", 25_000),
        _search_candidate("3", 20_000),
        _search_candidate("4", 15_000),
        _search_candidate("5", 12_000),
        _search_candidate("6", 9_000),   # below 10k threshold — should be dropped
        _search_candidate("7", 5_000),   # below 10k threshold — should be dropped
    ]
    selected = select_search_candidates_by_heat(candidates)
    titles = [c.item.title for c in selected]
    assert "Article 1" in titles
    assert "Article 5" in titles
    assert "Article 6" not in titles
    assert "Article 7" not in titles
    assert len(selected) == 5


def test_select_search_candidates_falls_back_to_top_15_when_fewer_than_5_high_heat():
    candidates = [
        _search_candidate("1", 30_000),
        _search_candidate("2", 25_000),
        _search_candidate("3", 8_000),   # below 10k
        _search_candidate("4", 7_000),   # below 10k
        _search_candidate("5", 6_000),   # below 10k
        _search_candidate("6", 5_000),   # below 10k
        _search_candidate("7", 4_000),   # below 10k
        _search_candidate("8", 3_000),   # below 10k
    ]
    # Only 2 with >=10k (< 5), so fall back to top 15 by heat desc.
    selected = select_search_candidates_by_heat(candidates)
    titles = [c.item.title for c in selected]
    assert titles == [
        "Article 1", "Article 2",  # the two 10k+ items
        "Article 3", "Article 4", "Article 5",
        "Article 6", "Article 7", "Article 8",
    ]


def test_select_search_candidates_caps_fallback_at_top_n():
    # 0 with 10k+ — all 20 should be sorted by heat desc, capped at fallback_top_n=15.
    candidates = [
        _search_candidate(str(i), 9_000 - i * 100) for i in range(20)
    ]
    selected = select_search_candidates_by_heat(candidates)
    assert len(selected) == 15
    # Top item by heat should be the first one (highest heat).
    assert selected[0].item.title == "Article 0"


def test_select_search_candidates_always_keeps_hot_board():
    hot_board_candidate = Candidate(
        item=_hb("99", 2_000_000, "Hot board item"),
        source_path=PATH_A,
        is_hot_board=True,
        preliminary_score=2.0,
    )
    candidates = [
        hot_board_candidate,
        _search_candidate("1", 30_000),
        _search_candidate("2", 9_000),  # below 10k
    ]
    selected = select_search_candidates_by_heat(candidates)
    titles = [c.item.title for c in selected]
    assert "Hot board item" in titles
    # The 10k+ search item passes; the 9k search item is dropped (since 5+ have 10k? no,
    # only 1 does, so fallback applies — but the 9k item is rank 2 in heat desc within
    # the fallback, and the cap is 15, so it's also kept).
    assert "Article 1" in titles


def test_select_search_candidates_handles_empty_input():
    assert select_search_candidates_by_heat([]) == []


def test_select_search_candidates_honors_custom_heat_selection():
    candidates = [
        _search_candidate("1", 6_000),
        _search_candidate("2", 5_500),
        _search_candidate("3", 5_000),
        _search_candidate("4", 4_500),
        _search_candidate("5", 4_000),
        _search_candidate("6", 3_500),
    ]
    # Custom: 5k threshold, need 3, fallback top 4.
    selected = select_search_candidates_by_heat(
        candidates,
        selection=HeatSelection(high_threshold=5_000, min_high_count=3, fallback_top_n=4),
    )
    titles = [c.item.title for c in selected]
    assert "Article 1" in titles
    assert "Article 3" in titles
    assert "Article 4" not in titles  # below 5k threshold
    assert "Article 5" not in titles


# ---------------------------------------------------------------------------
# build_hot_board_candidates (Path A only) + search gate
# ---------------------------------------------------------------------------


from heated_topics_v3.toutiao_paths import build_hot_board_candidates  # noqa: E402


def test_build_hot_board_candidates_returns_only_path_a():
    hot_board = [
        _hb("1", 2_000_000, "AI写作工具爆发", rank=1),
        _hb("2", 500_000, "Other below 1M", rank=2),  # below hot_board_min
        _hb("3", 3_000_000, "Unrelated news", rank=3),  # doesn't match persona
    ]
    candidates = build_hot_board_candidates(
        hot_board=hot_board,
        persona_keywords=("AI写作",),
        filters=PathFilters(hot_board_min=1_000_000),
    )
    paths = {c.source_path for c in candidates}
    assert paths == {PATH_A}
    titles = [c.item.title for c in candidates]
    assert "AI写作工具爆发" in titles
    assert "Other below 1M" not in titles
    assert "Unrelated news" not in titles


def test_build_candidates_skips_path_b_when_path_a_meets_gate():
    """With Path A ≥ min_hot_board_before_search, search items must be ignored."""
    hot_board = [
        _hb(str(i), 2_000_000, f"AI写作工具评测 {i}") for i in range(1, 7)
    ]  # 6 hot board items that match persona keyword "AI写作"
    search_items = [
        _search("100", "Search result ignored", article_heat=999_999),
    ]
    candidates = build_candidates(
        hot_board=hot_board,
        keywords=(ExtractedKeyword("AI写作", "热榜"),),
        persona_keywords=("AI写作",),
        search_results_by_keyword={"AI写作": search_items},
        article_info_by_url={
            "https://www.toutiao.com/group/100/": _info(999_999),
        },
        filters=PathFilters(
            hot_board_min=1_000_000,
            min_hot_board_before_search=5,
        ),
    )
    titles = [c.item.title for c in candidates]
    assert all(t.startswith("AI写作工具评测") for t in titles)
    assert "Search result ignored" not in titles
    assert all(c.source_path == PATH_A for c in candidates)


def test_build_candidates_runs_path_b_when_path_a_below_gate():
    """With Path A below threshold, search path must run normally."""
    hot_board = [
        _hb("1", 2_000_000, "AI写作工具霸榜"),  # 1 < 5
    ]
    candidates = build_candidates(
        hot_board=hot_board,
        keywords=(ExtractedKeyword("AI写作", "热榜"),),
        persona_keywords=("AI写作",),
        search_results_by_keyword={
            "AI写作": [_search("100", "Search result", article_heat=5000)],
        },
        article_info_by_url={
            "https://www.toutiao.com/group/100/": _info(5000),
        },
        filters=PathFilters(
            hot_board_min=1_000_000,
            min_hot_board_before_search=5,
        ),
    )
    titles = sorted(c.item.title for c in candidates)
    assert titles == ["AI写作工具霸榜", "Search result"]


def test_build_candidates_gate_threshold_is_configurable():
    """Lowering the gate to 1 should let a single hot board hit skip search."""
    hot_board = [
        _hb("1", 2_000_000, "AI写作工具霸榜"),
    ]
    candidates = build_candidates(
        hot_board=hot_board,
        keywords=(ExtractedKeyword("AI写作", "热榜"),),
        persona_keywords=("AI写作",),
        search_results_by_keyword={
            "AI写作": [_search("100", "Would be ignored", article_heat=5000)],
        },
        filters=PathFilters(
            hot_board_min=1_000_000,
            min_hot_board_before_search=1,
        ),
    )
    titles = [c.item.title for c in candidates]
    assert "AI写作工具霸榜" in titles
    assert "Would be ignored" not in titles
