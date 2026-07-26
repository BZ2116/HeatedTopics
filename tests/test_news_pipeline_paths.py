"""Tests for the platform-agnostic build_news_candidates helper."""
from __future__ import annotations

from heated_topics_v3.contracts import ExtractedKeyword, HeatMetrics, HotItem
from heated_topics_v3.news_pipeline_paths import (
    NewsPathContext,
    build_news_candidates,
)
from heated_topics_v3.toutiao_paths import (
    PATH_A,
    PATH_B,
    PATH_C,
    Candidate,
    PathFilters,
)


def _item(
    item_id: str,
    title: str,
    *,
    heat_value: int = 0,
    url: str | None = None,
    summary: str = "",
    raw: dict | None = None,
) -> HotItem:
    return HotItem(
        item_id=item_id,
        platform="test",
        item_type="topic",
        title=title,
        url=url or f"https://example.com/{item_id}",
        rank=1,
        heat=HeatMetrics(
            value=heat_value, label=str(heat_value), metric_name="hot_value",
            metrics={"hot_value": heat_value},
        ),
        summary=summary,
        category="",
        matched_query_ids=(),
        fetched_at="2026-07-26T00:00:00+08:00",
        fetch_status="success",
        raw_payload=raw or {},
    )


def _info(article_heat: int, is_toutiao_hot: bool = False) -> dict:
    return {"article_heat": article_heat, "is_toutiao_hot": is_toutiao_hot}


def _ctx() -> NewsPathContext:
    """A trivial context: identity_key=item_id; enrich returns input unchanged."""
    return NewsPathContext(
        identity_key=lambda item: item.item_id,
        enrich_with_article_info=lambda item, info: item,
        article_info_from_item=lambda item: None,
    )


def test_build_news_candidates_path_a_short_circuits_search():
    hot_board = [
        _item(f"hb{i}", f"Persona match {i}", heat_value=2_000_000)
        for i in range(5)
    ]
    candidates = build_news_candidates(
        hot_board=hot_board,
        keywords=(ExtractedKeyword("foo", "热榜"),),
        persona_keywords=("Persona",),
        search_results_by_keyword={
            "foo": [_item("sr1", "Search result ignored", heat_value=5000)],
        },
        article_info_by_key={"sr1": _info(5000)},
        filters=PathFilters(hot_board_min=1_000_000, min_hot_board_before_search=5),
        ctx=_ctx(),
    )
    titles = [c.item.title for c in candidates]
    assert all(t.startswith("Persona match") for t in titles)
    assert "Search result ignored" not in titles
    assert all(c.source_path == PATH_A for c in candidates)


def test_build_news_candidates_dedup_path_a_and_b_by_identity_key():
    same_id = "shared"
    hot_board = [_item(same_id, "Hot board hit", heat_value=2_000_000)]
    candidates = build_news_candidates(
        hot_board=hot_board,
        keywords=(ExtractedKeyword("foo", "热榜"),),
        persona_keywords=("Hot",),
        search_results_by_keyword={
            "foo": [_item(same_id, "Search dup", heat_value=2_000)],
        },
        article_info_by_key={same_id: _info(2_000)},
        filters=PathFilters(hot_board_min=1_000_000, article_heat_min=1_000),
        ctx=_ctx(),
    )
    assert len(candidates) == 1
    assert "+" in candidates[0].source_path
    assert PATH_A in candidates[0].source_path
    assert PATH_B in candidates[0].source_path


def test_build_news_candidates_includes_path_c_when_is_toutiao_hot():
    candidates = build_news_candidates(
        hot_board=[],
        keywords=(ExtractedKeyword("foo", "兜底"),),
        persona_keywords=("Low",),
        search_results_by_keyword={
            "foo": [_item("c1", "Low heat but Toutiao", heat_value=200)],
        },
        article_info_by_key={"c1": _info(200, is_toutiao_hot=True)},
        filters=PathFilters(
            article_heat_min=1_000,
            is_toutiao_hot_min_article_heat=0,
            is_toutiao_hot_max_article_heat=500,
        ),
        ctx=_ctx(),
    )
    assert len(candidates) == 1
    assert candidates[0].source_path == PATH_C
    assert candidates[0].is_toutiao_hot is True


def test_build_news_candidates_respects_article_heat_min():
    candidates = build_news_candidates(
        hot_board=[],
        keywords=(ExtractedKeyword("foo", "热榜"),),
        persona_keywords=("X",),
        search_results_by_keyword={
            "foo": [
                _item("ok", "Above min", heat_value=1500),
                _item("weak", "Below min", heat_value=100),
            ],
        },
        article_info_by_key={
            "ok": _info(1500),
            "weak": _info(100),
        },
        filters=PathFilters(article_heat_min=1_000),
        ctx=_ctx(),
    )
    titles = [c.item.title for c in candidates]
    assert "Above min" in titles
    assert "Below min" not in titles