import json
from pathlib import Path

from heated_topics_v3.pipeline import run_juejin_pipeline_v2

_RANK = json.dumps({"err_no": 0, "data": [
    {"content": {"content_id": "7001", "title": "AI Agent 实战", "brief": "b", "category_id": "1"},
     "content_counter": {"hot_rank": 1, "view": 5000, "like": 300, "collect": 100, "comment_count": 20, "interact_count": 400}},
]}, ensure_ascii=False)

_SEARCH = json.dumps({"err_no": 0, "data": [
    {"result_type": 2, "result_model": {"article_id": "7001", "article_info": {
        "title": "AI Agent 实战", "view_count": 5000, "digg_count": 300, "collect_count": 100, "comment_count": 20}}},
    {"result_type": 2, "result_model": {"article_id": "7002", "article_info": {
        "title": "MCP 协议解析", "view_count": 800, "digg_count": 40, "collect_count": 10, "comment_count": 3}}},
]}, ensure_ascii=False)

_DETAIL = json.dumps({"err_no": 0, "data": {
    "article_info": {"title": "AI Agent 实战", "mark_content": "正文内容 AI Agent。", "ctime": "1700000000"},
    "author_user_info": {"user_name": "作者"}, "tags": []}}, ensure_ascii=False)

_DETAIL_2 = json.dumps({"err_no": 0, "data": {
    "article_info": {"title": "MCP 协议解析", "mark_content": "正文内容 MCP。", "ctime": "1700000001"},
    "author_user_info": {"user_name": "作者B"}, "tags": []}}, ensure_ascii=False)


def _profile(tmp_path: Path) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "profile_id": "tech_ai_creator", "display_name": "Tech AI", "domains": ["tech"],
        "audience": ["devs"], "content_modes": ["analysis"], "preferred_platforms": ["juejin"],
        "core_keywords": ["AI Agent", "MCP"], "entity_keywords": [], "excluded_keywords": [],
    }), encoding="utf-8")
    return p


def _fetcher(url: str, timeout_seconds: int, body=None) -> str:
    if "article_rank" in url:
        return _RANK
    if "search_api" in url:
        return _SEARCH
    if "article/detail" in url:
        aid = (body or {}).get("article_id")
        return _DETAIL if aid == "7001" else _DETAIL_2
    raise AssertionError(f"unexpected url {url}")


def test_v2_merges_rank_and_search_dedups(tmp_path: Path):
    outputs = run_juejin_pipeline_v2(
        profile_path=_profile(tmp_path), output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=_fetcher, detail_fetcher=_fetcher,
    )
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    ids = sorted(row["item"]["item_id"] for row in hot_items)
    # 7001 来自 rank+search 去重后只一条；7002 来自 search；均命中关键词
    assert ids == ["juejin_7001", "juejin_7002"]
    report = outputs["report"].read_text(encoding="utf-8")
    assert "# Juejin 热点日报 v2" in report


# ---------- 对齐 Toutiao Path A/B：阈值门控 + 空关键词跳过 + 输出顺序 ----------

_RANK_5 = json.dumps({"err_no": 0, "data": [
    {"content": {"content_id": "9001", "title": "AI Agent 实战", "brief": "b", "category_id": "1"},
     "content_counter": {"hot_rank": 1, "view": 5000, "like": 300, "collect": 100, "comment_count": 20, "interact_count": 400}},
    {"content": {"content_id": "9002", "title": "MCP 协议解析", "brief": "b", "category_id": "1"},
     "content_counter": {"hot_rank": 2, "view": 4000, "like": 200, "collect": 80, "comment_count": 15, "interact_count": 300}},
    {"content": {"content_id": "9003", "title": "RAG 工程实践", "brief": "b", "category_id": "1"},
     "content_counter": {"hot_rank": 3, "view": 3500, "like": 180, "collect": 60, "comment_count": 10, "interact_count": 250}},
    {"content": {"content_id": "9004", "title": "向量数据库选型", "brief": "b", "category_id": "1"},
     "content_counter": {"hot_rank": 4, "view": 3000, "like": 150, "collect": 50, "comment_count": 8, "interact_count": 200}},
    {"content": {"content_id": "9005", "title": "Prompt 调优", "brief": "b", "category_id": "1"},
     "content_counter": {"hot_rank": 5, "view": 2500, "like": 120, "collect": 40, "comment_count": 6, "interact_count": 150}},
]}, ensure_ascii=False)


def _profile_many_kw(tmp_path: Path) -> Path:
    """profile 包含 5+ 个均与 _RANK_5 标题匹配的 core_keywords，确保 Path A ≥ 5。"""
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "profile_id": "tech_ai_creator", "display_name": "Tech AI", "domains": ["tech"],
        "audience": ["devs"], "content_modes": ["analysis"], "preferred_platforms": ["juejin"],
        # 5 个关键词均与 _RANK_5 标题中的子串匹配
        "core_keywords": ["AI Agent", "MCP", "RAG", "向量数据库", "Prompt"],
        "entity_keywords": [], "excluded_keywords": [],
    }), encoding="utf-8")
    return p


def test_v2_skips_search_when_rank_match_count_meets_threshold(tmp_path: Path):
    """对齐 Toutiao：Path A persona 匹配 ≥ min_hot_board_before_search → 跳过 search。"""
    search_calls = {"n": 0}

    def fetcher(url: str, timeout_seconds: int, body=None) -> str:
        if "article_rank" in url:
            return _RANK_5
        if "search_api" in url:
            search_calls["n"] += 1
            return _SEARCH
        if "article/detail" in url:
            aid = (body or {}).get("article_id")
            return _DETAIL if aid == "7001" else _DETAIL_2
        raise AssertionError(f"unexpected url {url}")

    run_juejin_pipeline_v2(
        profile_path=_profile_many_kw(tmp_path), output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=fetcher, detail_fetcher=fetcher,
        min_hot_board_before_search=5,
    )
    # search 完全未调用
    assert search_calls["n"] == 0


def test_v2_skips_search_when_keywords_empty(tmp_path: Path):
    """对齐 Toutiao：core_keywords 为空 → 跳过整个 search 阶段。"""
    search_calls = {"n": 0}

    def fetcher(url: str, timeout_seconds: int, body=None) -> str:
        if "search_api" in url:
            search_calls["n"] += 1
            return _SEARCH
        if "article_rank" in url:
            return _RANK
        if "article/detail" in url:
            return _DETAIL
        raise AssertionError(f"unexpected url {url}")

    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "profile_id": "x", "display_name": "X", "domains": ["tech"],
        "audience": ["a"], "content_modes": ["m"], "preferred_platforms": ["juejin"],
        "core_keywords": [], "entity_keywords": [], "excluded_keywords": [],
    }), encoding="utf-8")
    run_juejin_pipeline_v2(
        profile_path=p, output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=fetcher, detail_fetcher=fetcher,
    )
    assert search_calls["n"] == 0


def test_v2_orders_path_a_before_path_b(tmp_path: Path):
    """对齐 Toutiao：rank 项（Path A）在 search 项（Path B）之前。"""
    outputs = run_juejin_pipeline_v2(
        profile_path=_profile(tmp_path), output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=_fetcher, detail_fetcher=_fetcher,
    )
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    # 7001 来自 rank（A），7002 来自 search（B）。合并后顺序：A 在前 → B 在后
    ids = [row["item"]["item_id"] for row in hot_items]
    assert ids == ["juejin_7001", "juejin_7002"]
    # 7001 来自 rank，source_path=A；7002 仅来自 search，source_path=B
    a_item = next(r for r in hot_items if r["item"]["item_id"] == "juejin_7001")
    b_item = next(r for r in hot_items if r["item"]["item_id"] == "juejin_7002")
    assert a_item["item"]["raw_payload"]["source_path"] == "A"
    assert b_item["item"]["raw_payload"]["source_path"] == "B"