import json
from pathlib import Path

import pytest

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
        use_llm_rerank=False,
        top_n=10,
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=detail_fetcher,
        llm_caller=llm,
    )

    assert result.user_id == "zhao_001"
    assert result.date == "2026-07-13"
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