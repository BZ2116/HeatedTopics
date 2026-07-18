import json
import inspect
from pathlib import Path

import pytest

from heated_topics_v3.hot_board_cache import utc8_today
from heated_topics_v3.pipeline import run_toutiao_pipeline_v2


V2_PROFILE = {
    "user_id": "zhao_001",
    "level1": "科技AI",
    "level2": "AI工具应用",
    "personal": {
        "role": "经管学生视角的AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习", "办公"],
        "value": "真实使用建议",
    },
    "core_keywords": ["AI工具", "AI写作"],
}


def test_pipeline_has_no_llm_rerank_option():
    assert "use_llm_rerank" not in inspect.signature(run_toutiao_pipeline_v2).parameters


def _write_profile(tmp_path: Path, payload: dict | None = None) -> Path:
    profile_path = tmp_path / "zhao_001.json"
    profile_path.write_text(
        json.dumps(payload or V2_PROFILE, ensure_ascii=False),
        encoding="utf-8",
    )
    return profile_path


def _write_legacy_profile(tmp_path: Path) -> Path:
    legacy = {
        "profile_id": "tech_ai_creator",
        "display_name": "Tech AI Creator",
        "domains": ["tech", "ai"],
        "audience": ["developers"],
        "content_modes": ["analysis"],
        "preferred_platforms": ["toutiao"],
        "core_keywords": ["AI Agent"],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    return path


def _static_llm_caller():
    def caller(prompt: str, *, system: str | None = None, **_kwargs) -> str:
        return json.dumps(
            [
                {"keyword": "AI写作工具", "match_expectation": "热榜"},
                {"keyword": "AI办公助手", "match_expectation": "热榜"},
                {"keyword": "Claude Code", "match_expectation": "热榜"},
                {"keyword": "MCP", "match_expectation": "长尾"},
                {"keyword": "Cursor", "match_expectation": "兜底"},
            ],
            ensure_ascii=False,
        )

    return caller


def _fake_fetchers():
    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps(
                {
                    "status": "success",
                    "data": [
                        {
                            "ClusterId": "1",
                            "Title": "AI写作工具霸榜今日",
                            "Url": "https://www.toutiao.com/group/1/",
                            "HotValue": 2_000_000,
                            "QueryWord": "AI写作工具霸榜今日",
                        },
                        {
                            "ClusterId": "2",
                            "Title": "其他无关新闻",
                            "Url": "https://www.toutiao.com/group/2/",
                            "HotValue": 800_000,
                            "QueryWord": "其他",
                        },
                    ],
                }
            )
        if "/i" in url and "/info" in url:
            article_id_match = url.split("/i")[-1].split("/")[0]
            return json.dumps(
                {
                    "data": {
                        "impression_count": 500,
                        "digg_count": 30,
                        "comment_count": 8,
                        "repost_count": 0,
                        "repin_count": 2,
                        "is_toutiao_hot": True,
                        "is_original": False,
                        "content": "<p>Article body here</p>",
                    }
                }
            )
        if "so.toutiao.com/search" in url:
            offset = "10" if "offset=10" in url else "0"
            if offset == "0":
                return json.dumps(
                    {
                        "dom": (
                            '<div class="r"><a href="https://www.toutiao.com/group/100/">'
                            'AI写作工具评测</a></div>'
                        ),
                        "count": 1,
                    }
                )
            return json.dumps({"dom": "", "count": 0})
        return ""

    def detail_fetcher(url: str, timeout_seconds: int) -> str:
        return (
            "<html><body><article>"
            "<h1>Article Body</h1><p>This is a Toutiao article body used in tests.</p>"
            "</article></body></html>"
        )

    return fetcher, detail_fetcher


def test_run_toutiao_pipeline_v2_writes_per_user_output(tmp_path: Path):
    profile_path = _write_profile(tmp_path)
    fetcher, detail_fetcher = _fake_fetchers()
    llm = _static_llm_caller()

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        use_llm_keywords=True,
        use_llm_summary=False,
        top_n=10,
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=llm,
    )

    assert result.user_id == "zhao_001"
    assert result.date == utc8_today()
    assert result.run_dir.exists()
    assert result.report_path.exists()
    assert result.focused_path.exists()
    assert (result.run_dir / "raw" / "hot_board.json").exists()
    assert (result.run_dir / "raw" / "article_info.json").exists()
    assert any((result.run_dir / "raw").glob("search_*.json"))

    report = result.report_path.read_text(encoding="utf-8")
    assert "头条热点日报 — zhao_001" in report
    assert "AI写作工具" in report or "AI写作工具霸榜" in report

    focused = json.loads(result.focused_path.read_text(encoding="utf-8"))
    assert focused["user_id"] == "zhao_001"
    assert focused["top_n"] == len(focused["results"])
    assert focused["candidates_total"] >= 1

    keywords_cache = tmp_path / "cache" / "core_keywords" / "zhao_001.json"
    assert keywords_cache.exists()

    hot_board_cache = tmp_path / "cache" / "hot_board" / f"{result.date}.json"
    assert hot_board_cache.exists()


def test_run_toutiao_pipeline_v2_uses_cached_hot_board(tmp_path: Path):
    profile_path = _write_profile(tmp_path)
    fetcher, detail_fetcher = _fake_fetchers()
    llm = _static_llm_caller()

    run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=llm,
    )

    call_count = {"hot_board": 0}

    def counting_fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            call_count["hot_board"] += 1
            return json.dumps({"status": "success", "data": []})
        return ""

    run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T11:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=counting_fetcher,
        article_info_fetcher=counting_fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=llm,
    )

    assert call_count["hot_board"] == 0, "hot board should hit cache on second run"


def test_run_toutiao_pipeline_v2_persona_change_invalidates_keyword_cache(tmp_path: Path):
    profile_a = tmp_path / "a.json"
    profile_a.write_text(json.dumps(V2_PROFILE, ensure_ascii=False), encoding="utf-8")
    profile_b_data = json.loads(json.dumps(V2_PROFILE))
    profile_b_data["personal"]["subject"] = "AI Agent"
    profile_b = tmp_path / "b.json"
    profile_b.write_text(json.dumps(profile_b_data, ensure_ascii=False), encoding="utf-8")

    fetcher, detail_fetcher = _fake_fetchers()
    llm = _static_llm_caller()

    run_toutiao_pipeline_v2(
        profile_path=profile_a,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=llm,
    )

    call_count = {"llm": 0}

    def counting_llm(prompt: str, *, system: str | None = None, **_kwargs) -> str:
        call_count["llm"] += 1
        return json.dumps(
            [{"keyword": "AI Agent", "match_expectation": "热榜"}] * 6,
            ensure_ascii=False,
        )

    run_toutiao_pipeline_v2(
        profile_path=profile_b,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T11:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=counting_llm,
    )

    assert call_count["llm"] >= 1, "persona change should invalidate keyword cache"


def test_run_toutiao_pipeline_v2_legacy_profile_raises(tmp_path: Path):
    legacy_path = _write_legacy_profile(tmp_path)
    fetcher, detail_fetcher = _fake_fetchers()
    with pytest.raises(ValueError) as exc_info:
        run_toutiao_pipeline_v2(
            profile_path=legacy_path,
            output_root=tmp_path / "output",
            fetched_at="2026-07-13T10:00:00+08:00",
            hot_board_cache_root=tmp_path / "cache",
            persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
            llm_cache_root=tmp_path / "cache" / "llm",
            fetcher=fetcher,
            article_info_fetcher=fetcher,
            detail_fetcher=detail_fetcher,
            llm_caller=_static_llm_caller(),
        )
    assert "legacy" in str(exc_info.value).lower()


def test_run_toutiao_pipeline_v2_no_llm_falls_back_to_core(tmp_path: Path):
    profile_path = _write_profile(tmp_path)
    fetcher, detail_fetcher = _fake_fetchers()

    def boom(*_args, **_kwargs):
        raise AssertionError("LLM should not be called when use_llm_keywords=False")

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        use_llm_keywords=False,
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=boom,
    )

    assert result.keyword_source in {"no_llm", "fallback_core"}


def test_run_toutiao_pipeline_v2_resolves_jump_url_to_article_info(tmp_path: Path):
    """Search returns /search/jump URLs whose article_id is buried in h5_url.

    The pipeline must resolve the jump URL first so article_info can be called
    with the real article_id, then attach article_heat to the resulting candidate.
    """
    profile_path = _write_profile(tmp_path)

    jump_url = (
        "https://so.toutiao.com/search/jump?aid=1455&url="
        "https%3A%2F%2Farticle.zlink.toutiao.com%2Fabcd%3Fh5_url%3D"
        "https%253A%252F%252Ftoutiao.com%252Fgroup%252F7661087635032638003%252F"
    )
    info_url_seen: list[str] = []

    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps(
                {
                    "status": "success",
                    "data": [
                        {
                            "ClusterId": "1",
                            "Title": "AI写作工具霸榜今日",
                            "Url": "https://www.toutiao.com/group/1/",
                            "HotValue": 2_000_000,
                            "QueryWord": "AI写作工具霸榜今日",
                        },
                    ],
                }
            )
        if "so.toutiao.com/search" in url:
            return json.dumps(
                {
                    "dom": f'<div class="r"><a href="{jump_url}">AI写作工具评测</a></div>',
                    "count": 1,
                }
            )
        if "/i" in url and "/info" in url:
            info_url_seen.append(url)
            return json.dumps(
                {
                    "data": {
                        "impression_count": 8000,
                        "digg_count": 200,
                        "comment_count": 50,
                        "repost_count": 10,
                        "repin_count": 5,
                        "is_toutiao_hot": True,
                        "is_original": False,
                        "content": "<p>Resolved article body</p>",
                    }
                }
            )
        return ""

    def detail_fetcher(url: str, timeout_seconds: int) -> str:
        return "<html><body><article><p>body</p></article></body></html>"

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=_static_llm_caller(),
    )

    # The article_info fetcher must have been called with the resolved article_id.
    assert info_url_seen, "article_info fetcher should have been called"
    assert "7661087635032638003" in info_url_seen[0]
    assert "m.toutiao.com/i7661087635032638003/info" in info_url_seen[0]

    # The candidate should carry the resolved article_heat (impression*1 + digg*2 +
    # comment*5 + repost*10 + repin*3 = 8000 + 400 + 250 + 100 + 15 = 8765).
    focused = json.loads(result.focused_path.read_text(encoding="utf-8"))
    assert focused["candidates_total"] >= 1
    top_results = focused.get("results", [])
    assert top_results, "adaptive selection should keep the resolved candidate"
    found_heat = any(
        r.get("article_heat") == 8765 for r in top_results
    )
    assert found_heat, "resolved search item should appear in top results with article_heat=8765"


def test_pipeline_v2_skips_search_when_hot_board_meets_gate(tmp_path: Path):
    """When Path A yields ≥ min_hot_board_before_search candidates, the search
    fetcher must NOT be called. Per persona, these hot board items must all
    match a persona keyword for Path A to count them.

    Note: article_info IS still called once per top candidate so hot-board
    items get a body fallback (the desktop HTML page is JS-rendered and
    ``parse_toutiao_article_page`` can't crack it). The search fetcher, by
    contrast, is what the gate controls.
    """
    profile_path = _write_profile(tmp_path)
    call_counts = {"search": 0, "info": 0, "detail": 0}

    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            # 6 hot board items, all persona-matched. Titles contain core keyword "AI工具".
            return json.dumps(
                {
                    "status": "success",
                    "data": [
                        {
                            "ClusterId": str(i),
                            "Title": f"AI工具评测 {i}",
                            "Url": f"https://www.toutiao.com/group/{i}/",
                            "HotValue": 2_000_000,
                            "QueryWord": "AI工具评测",
                        }
                        for i in range(1, 7)
                    ],
                }
            )
        if "so.toutiao.com/search" in url:
            call_counts["search"] += 1
            return json.dumps({"dom": "", "count": 0})
        if "/i" in url and "/info" in url:
            call_counts["info"] += 1
            return json.dumps({"data": {}})
        return ""

    def detail_fetcher(url: str, timeout_seconds: int) -> str:
        call_counts["detail"] += 1
        return "<html><body><article><p>body</p></article></body></html>"

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=_static_llm_caller(),
    )

    assert call_counts["search"] == 0, "search fetcher must not be called when gate is met"
    # article_info IS called for top candidates (here: 6 Path A items, top_n=10
    # so all 6 get the body fallback call).
    assert call_counts["info"] == 6, (
        "article_info must be called once per top Path A candidate so its body has a fallback"
    )
    focused = json.loads(result.focused_path.read_text(encoding="utf-8"))
    assert focused["candidates_total"] >= 5
    top_results = focused.get("results", [])
    assert all(r.get("source_path") == "A" for r in top_results)


def test_pipeline_v2_runs_search_when_hot_board_below_gate(tmp_path: Path):
    """When Path A yields < min_hot_board_before_search, search MUST run."""
    profile_path = _write_profile(tmp_path)
    call_counts = {"search": 0, "info": 0}

    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps(
                {
                    "status": "success",
                    "data": [
                        {
                            "ClusterId": "1",
                            "Title": "AI工具霸榜",
                            "Url": "https://www.toutiao.com/group/1/",
                            "HotValue": 2_000_000,
                            "QueryWord": "AI工具霸榜",
                        },
                    ],
                }
            )
        if "so.toutiao.com/search" in url:
            call_counts["search"] += 1
            return json.dumps(
                {
                    "dom": '<div class="r"><a href="https://www.toutiao.com/group/100/">'
                    'AI写作工具评测</a></div>',
                    "count": 1,
                }
            )
        if "/i" in url and "/info" in url:
            call_counts["info"] += 1
            return json.dumps(
                {
                    "data": {
                        "impression_count": 500,
                        "digg_count": 30,
                        "comment_count": 8,
                        "repost_count": 0,
                        "repin_count": 2,
                        "is_toutiao_hot": True,
                        "is_original": False,
                        "content": "<p>body</p>",
                    }
                }
            )
        return ""

    def detail_fetcher(url: str, timeout_seconds: int) -> str:
        return "<html><body><article><p>body</p></article></body></html>"

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=_static_llm_caller(),
    )

    assert call_counts["search"] >= 1, "search must run when Path A < gate"
    focused = json.loads(result.focused_path.read_text(encoding="utf-8"))
    paths_seen = {r.get("source_path") for r in focused.get("results", [])}
    assert "B" in paths_seen


def test_pipeline_v2_enriches_path_a_with_article_info(tmp_path: Path):
    """Regression: Path A hot-board items must go through article_info so the
    article body has a fallback when the desktop page is JS-rendered.

    Without the enrichment, parse_toutiao_article_page returns 'empty' for
    the hot-board item, _partial_detail has no content_html on hand, and the
    article file ends up with no body.
    """
    # Use a 非遗 persona so the hot-board 美国游客 item matches Path A.
    profile_payload = dict(V2_PROFILE)
    profile_payload["personal"] = dict(V2_PROFILE["personal"])
    profile_payload["personal"]["subject"] = "非遗"
    profile_payload["core_keywords"] = ["非遗"]
    profile_path = tmp_path / "feiyi.json"
    profile_path.write_text(json.dumps(profile_payload, ensure_ascii=False), encoding="utf-8")

    info_calls: list[str] = []
    hot_board_id = "7662378373842681898"

    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps(
                {
                    "status": "success",
                    "data": [
                        {
                            "ClusterId": hot_board_id,
                            "Title": "美国游客在张家界沉浸式体验非遗",
                            "Url": f"https://www.toutiao.com/trending/{hot_board_id}/",
                            "HotValue": 5_303_636,
                            "QueryWord": "非遗",
                        },
                    ],
                }
            )
        if "/i" in url and "/info" in url:
            info_calls.append(url)
            return json.dumps(
                {
                    "data": {
                        "impression_count": 100,
                        "digg_count": 10,
                        "comment_count": 5,
                        "repost_count": 0,
                        "repin_count": 0,
                        "is_toutiao_hot": False,
                        "is_original": False,
                        "content": "<p>张家界非遗体验正文 from article_info</p>",
                    }
                }
            )
        return ""

    # detail_fetcher returns HTML without an <article> tag, simulating the
    # JS-rendered desktop page that parse_toutiao_article_page can't crack.
    def detail_fetcher(url: str, timeout_seconds: int) -> str:
        return "<html><body><div id='render-root'></div></body></html>"

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-15T08:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=_static_llm_caller(),
    )

    assert any(hot_board_id in url for url in info_calls), (
        "article_info must be called for the hot-board item so its body has a fallback"
    )
    articles_dir = result.run_dir / "articles"
    bodies = {p.read_text(encoding="utf-8") for p in articles_dir.glob("*.txt")}
    matching = [text for text in bodies if "张家界非遗体验正文 from article_info" in text]
    assert matching, (
        "expected the hot-board article file body to carry article_info content, "
        f"got files: {sorted(p.name for p in articles_dir.glob('*.txt'))}"
    )
