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


def test_pipeline_shares_daily_search_cache_across_users(tmp_path: Path):
    search_calls = 0

    def search_fetcher(url: str, _timeout_seconds: int) -> str:
        nonlocal search_calls
        if "hot-event/hot-board" in url:
            return json.dumps(
                {
                    "status": "success",
                    "data": [
                        {
                            "ClusterId": "88",
                            "Title": "无关低热度新闻",
                            "Url": "https://www.toutiao.com/group/88/",
                            "HotValue": 10,
                            "QueryWord": "无关内容",
                        }
                    ],
                }
            )
        if "so.toutiao.com/search" in url:
            search_calls += 1
            return json.dumps(
                {
                    "dom": (
                        '<div class="r"><a href="https://www.toutiao.com/group/901/">'
                        "共享关键词文章</a></div>"
                    ),
                    "count": 1,
                }
            )
        raise AssertionError(f"unexpected search fetch: {url}")

    def article_info_fetcher(_url: str, _timeout_seconds: int) -> str:
        return json.dumps(
            {
                "data": {
                    "impression_count": 1_000,
                    "digg_count": 20,
                    "comment_count": 5,
                    "repost_count": 0,
                    "repin_count": 0,
                    "is_toutiao_hot": False,
                    "content": "<p>共享正文</p>",
                }
            }
        )

    def detail_fetcher(_url: str, _timeout_seconds: int) -> str:
        return "<html><body><article><p>共享正文</p></article></body></html>"

    for user_id in ("user_a", "user_b"):
        payload = json.loads(json.dumps(V2_PROFILE, ensure_ascii=False))
        payload["user_id"] = user_id
        payload["core_keywords"] = ["共享关键词"]
        profile_path = tmp_path / f"{user_id}.json"
        profile_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        run_toutiao_pipeline_v2(
            profile_path=profile_path,
            output_root=tmp_path / "output",
            fetched_at="2026-07-18T10:00:00+08:00",
            hot_board_cache_root=tmp_path / "cache",
            top_n=10,
            fetcher=search_fetcher,
            article_info_fetcher=article_info_fetcher,
            detail_fetcher=detail_fetcher,
        )

    assert search_calls == 1


def test_pipeline_stops_keyword_search_at_budget_and_keeps_completed_results(tmp_path: Path):
    now = [0.0]
    search_keywords: list[str] = []
    timeouts: list[int] = []

    payload = json.loads(json.dumps(V2_PROFILE, ensure_ascii=False))
    payload["core_keywords"] = ["关键词一", "关键词二", "关键词三"]
    profile_path = tmp_path / "budget.json"
    profile_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps(
                {
                    "status": "success",
                    "data": [{
                        "ClusterId": "77",
                        "Title": "无关低热度新闻",
                        "Url": "https://www.toutiao.com/group/77/",
                        "HotValue": 10,
                        "QueryWord": "无关内容",
                    }],
                }
            )
        if "so.toutiao.com/search" in url:
            from urllib.parse import parse_qs, urlparse

            search_keywords.append(parse_qs(urlparse(url).query)["keyword"][0])
            timeouts.append(timeout_seconds)
            now[0] = 20.1
            return json.dumps(
                {
                    "dom": (
                        '<div class="r"><a href="https://www.toutiao.com/group/911/">'
                        "预算内文章</a></div>"
                    ),
                    "count": 1,
                }
            )
        raise AssertionError(url)

    def article_info_fetcher(_url: str, _timeout_seconds: int) -> str:
        return json.dumps({"data": {"impression_count": 1_000, "content": "正文"}})

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-18T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        fetcher=fetcher,
        article_info_fetcher=article_info_fetcher,
        detail_fetcher=lambda _url, _timeout: "<article>正文</article>",
        search_phase_budget_seconds=20.0,
        _monotonic=lambda: now[0],
    )

    assert search_keywords == ["关键词一"]
    assert timeouts == [20]
    assert result.candidates_total >= 1
