from heated_topics_v3.contracts import ExtractedKeyword, HeatMetrics, HotItem
from heated_topics_v3.toutiao_paths import (
    PATH_A,
    PATH_B,
    PATH_C,
    Candidate,
    PathFilters,
    apply_llm_rerank,
    build_candidates,
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
    return HotItem(
        item_id=f"search_{article_id}",
        platform="toutiao",
        item_type="search_result",
        title=title,
        url=f"https://www.toutiao.com/group/{article_id}/",
        rank=1,
        heat=HeatMetrics(
            value=article_heat, label=str(article_heat), metric_name="article_heat", metrics={},
        ),
        summary="",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={"source_kind": "article_info", "search_phrase": "AI写作"},
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


def test_apply_llm_rerank_reorders_top_k():
    candidates = [
        Candidate(
            item=_search("1", "First", article_heat=2000), source_path=PATH_B,
            matched_keyword="AI写作", preliminary_score=6.6,
        ),
        Candidate(
            item=_search("2", "Second", article_heat=3000), source_path=PATH_B,
            matched_keyword="AI写作", preliminary_score=6.9,
        ),
        Candidate(
            item=_search("3", "Third", article_heat=1500), source_path=PATH_B,
            matched_keyword="AI写作", preliminary_score=6.4,
        ),
    ]

    # After score-sort: [Second(idx0), First(idx1), Third(idx2)].
    # LLM returns: idx2 (Third) -> rank1, idx0 (Second) -> rank2, idx1 (First) -> rank3.
    def fake_llm(prompt: str, *, system: str | None = None, **_kwargs) -> str:
        return '[{"index": 2, "final_rank": 1}, {"index": 0, "final_rank": 2}, {"index": 1, "final_rank": 3}]'

    reranked = apply_llm_rerank(candidates, llm=fake_llm, top_n_for_rerank=3)
    titles = [c.item.title for c in reranked]
    assert titles == ["Third", "Second", "First"]


def test_apply_llm_rerank_falls_back_to_input_on_llm_unavailable():
    from heated_topics_v3.llm_client import LLMUnavailable

    candidates = [
        Candidate(
            item=_search("1", "A", article_heat=2000), source_path=PATH_B, preliminary_score=6.6,
        ),
        Candidate(
            item=_search("2", "B", article_heat=3000), source_path=PATH_B, preliminary_score=6.9,
        ),
    ]

    def boom(*_args, **_kwargs):
        raise LLMUnavailable("network down")

    reranked = apply_llm_rerank(candidates, llm=boom)
    assert reranked == candidates


def test_apply_llm_rerank_falls_back_when_json_invalid():
    candidates = [
        Candidate(
            item=_search("1", "A", article_heat=2000), source_path=PATH_B, preliminary_score=6.6,
        ),
    ]

    def fake_llm(*_args, **_kwargs):
        return "not a json array"

    reranked = apply_llm_rerank(candidates, llm=fake_llm)
    assert reranked == candidates