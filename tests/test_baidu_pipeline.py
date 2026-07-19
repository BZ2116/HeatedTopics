import json
from pathlib import Path

from heated_topics_v3.pipeline import run_baidu_pipeline


def test_run_baidu_pipeline_writes_dataset_and_report(tmp_path: Path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech", "ai"],
                "audience": ["developers"],
                "content_modes": ["tutorial", "analysis"],
                "preferred_platforms": ["baidu"],
                "core_keywords": ["AI Agent", "MCP"],
                "entity_keywords": ["Claude Code"],
                "excluded_keywords": [],
            }
        ),
        encoding="utf-8",
    )

    board_json = json.dumps(
        {
            "success": True,
            "data": {"cards": [{"component": "tabTextList", "content": [
                {"content": [
                    {"isTop": True, "word": "AI Agent 发布", "url": "https://m.baidu.com/s?word=AI-Agent"},
                    {"isTop": False, "index": 1, "word": "MCP 全景", "url": "https://m.baidu.com/s?word=MCP", "hotTag": "3"},
                    {"isTop": False, "index": 2, "word": "无关新闻", "url": "https://m.baidu.com/s?word=other", "hotTag": "1"},
                ]}
            ]}]},
        },
        ensure_ascii=False,
    )

    search_html = """
<html><body>
<a href="https://baijiahao.baidu.com/s?id=1110000000000000001">AI Agent 实战</a>
<a href="https://baijiahao.baidu.com/s?id=2220000000000000002">MCP 工具集</a>
</body></html>
"""

    article_html = """
<html><body>
<article>
<p>这是一篇关于 AI Agent 的实战文章。</p>
<p>本文详细讨论了 MCP 协议的工作方式。</p>
</article>
</body></html>
"""

    def board_fetcher(url: str, timeout_seconds: int) -> str:
        return board_json

    def search_fetcher(url: str, timeout_seconds: int) -> str:
        return search_html

    def article_fetcher(url: str, timeout_seconds: int) -> str:
        return article_html

    outputs = run_baidu_pipeline(
        profile_path=profile_path,
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-19T20:00:00+08:00",
        cache_root=tmp_path / "cache",
        top_n=10,
        fetcher=board_fetcher,
        search_fetcher=search_fetcher,
        article_fetcher=article_fetcher,
    )

    run_dir = tmp_path / "outputs" / "tech_ai_creator" / "baidu" / "run_20260719_200000"
    assert set(outputs) == {"article_texts", "hot_items", "report"}
    assert outputs["hot_items"].parent == run_dir
    assert outputs["report"].name == "report.md"
    assert outputs["hot_items"].name == "hot_items.json"

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    text_files = sorted(outputs["article_texts"].glob("*.txt"))

    # Two words matched core keywords: "AI Agent 发布" and "MCP 全景".
    # Each yields one baijiahao article; "无关新闻" matches nothing.
    assert len(hot_items) == 2
    titles = [row["item"]["title"] for row in hot_items]
    assert titles == ["AI Agent 发布", "MCP 全景"]
    for row in hot_items:
        assert row["detail"]["fetch_status"] == "success"
        assert row["detail"]["extraction_method"] == "baijiahao_article_page"
        assert row["detail"]["txt_path"].startswith("article_texts/")
    assert len(text_files) == 2

    report = outputs["report"].read_text(encoding="utf-8")
    assert "# Baidu 热搜日报" in report
    assert "AI Agent 发布" in report
    assert "MCP 全景" in report


def test_run_baidu_pipeline_is_all_transparent_when_no_match(tmp_path: Path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech"],
                "audience": ["devs"],
                "content_modes": ["tutorial"],
                "preferred_platforms": ["baidu"],
                "core_keywords": ["NoSuchWord"],
                "entity_keywords": [],
                "excluded_keywords": [],
            }
        ),
        encoding="utf-8",
    )

    board_json = json.dumps(
        {"success": True, "data": {"cards": [{"component": "tabTextList", "content": [
            {"content": [{"isTop": True, "word": "无关新闻", "url": "https://m.baidu.com/s?word=other"}]}
        ]}]}},
        ensure_ascii=False,
    )

    outputs = run_baidu_pipeline(
        profile_path=profile_path,
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-19T20:00:00+08:00",
        cache_root=tmp_path / "cache",
        fetcher=lambda u, t: board_json,
        search_fetcher=lambda u, t: "<html></html>",
        article_fetcher=lambda u, t: "<html></html>",
    )

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert hot_items == []
    report = outputs["report"].read_text(encoding="utf-8")
    assert "本次未抓到任何条目" in report
