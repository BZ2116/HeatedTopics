import json
import urllib.parse
from pathlib import Path

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
    path = tmp_path / "zhao_001.json"
    path.write_text(json.dumps(payload or V2_PROFILE, ensure_ascii=False), encoding="utf-8")
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


def _recording_fetcher(searched_urls: list[str], hot_board_data: list | None = None):
    default_board = hot_board_data if hot_board_data is not None else [
        {
            "ClusterId": "999",
            "Title": "无关新闻占位",
            "Url": "https://www.toutiao.com/group/999/",
            "HotValue": 100,
            "QueryWord": "占位",
        }
    ]

    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps({"status": "success", "data": default_board})
        if "so.toutiao.com/search" in url:
            searched_urls.append(urllib.parse.unquote(url))
            return json.dumps({"dom": "", "count": 0})
        if "/i" in url and "/info" in url:
            return json.dumps({"data": {}})
        return ""

    return fetcher


def _detail_fetcher(url: str, timeout_seconds: int) -> str:
    return "<html><body><article><p>body</p></article></body></html>"


def _run(tmp_path, *, custom_keywords=(), on_search_committed=None, fetcher=None,
         hot_board_data=None, searched_urls=None):
    profile_path = _write_profile(tmp_path)
    if fetcher is None:
        searched_urls = searched_urls if searched_urls is not None else []
        fetcher = _recording_fetcher(searched_urls, hot_board_data)
    return run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        custom_keywords=custom_keywords,
        on_search_committed=on_search_committed,
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=_detail_fetcher,
        llm_caller=_static_llm_caller(),
    )


def test_custom_keywords_sets_source_custom(tmp_path: Path):
    result = _run(tmp_path, custom_keywords=("比特币", "美联储"))
    assert result.keyword_source == "custom"
    assert result.keyword_count == 2


def test_custom_keywords_searched_not_auto(tmp_path: Path):
    searched: list[str] = []
    _run(tmp_path, custom_keywords=("比特币", "美联储"), searched_urls=searched)
    joined = " ".join(searched)
    assert "比特币" in joined and "美联储" in joined
    assert "AI写作工具" not in joined and "AI办公助手" not in joined


def test_custom_keywords_preserve_order(tmp_path: Path):
    searched: list[str] = []
    _run(tmp_path, custom_keywords=("比特币", "美联储"), searched_urls=searched)
    first_bitcoin = min(i for i, u in enumerate(searched) if "比特币" in u)
    first_fed = min(i for i, u in enumerate(searched) if "美联储" in u)
    assert first_bitcoin < first_fed


def test_empty_custom_keywords_fallback_to_auto(tmp_path: Path):
    result = _run(tmp_path, custom_keywords=())
    assert result.keyword_source != "custom"


def test_search_triggered_calls_commit_callback(tmp_path: Path):
    calls: list[int] = []
    _run(tmp_path, custom_keywords=("比特币",), on_search_committed=lambda: calls.append(1))
    assert calls == [1]


def test_skip_search_does_not_call_commit_callback(tmp_path: Path):
    """6 hot-board items all matching core keyword 'AI工具' meet the search gate,
    so skip_search is True and the commit callback must NOT fire."""
    calls: list[int] = []
    hot_board = [
        {
            "ClusterId": str(i),
            "Title": f"AI工具评测 {i}",
            "Url": f"https://www.toutiao.com/group/{i}/",
            "HotValue": 2_000_000,
            "QueryWord": "AI工具评测",
        }
        for i in range(1, 7)
    ]
    _run(tmp_path, custom_keywords=(), on_search_committed=lambda: calls.append(1),
         hot_board_data=hot_board)
    assert calls == []
