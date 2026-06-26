import json

from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CandidateTopic


def test_write_jsonl_creates_parent_directory(tmp_path):
    path = tmp_path / "data/search_discovery/raw/search_results.jsonl"

    write_jsonl(path, [{"title": "AI Agent 新闻"}])

    assert path.read_text(encoding="utf-8").strip() == '{"title": "AI Agent 新闻"}'


def test_write_json_creates_readable_json(tmp_path):
    path = tmp_path / "data/search_discovery/processed/search_topic_index.json"

    write_json(path, {"topics": [{"title": "AI Agent 新闻"}]})

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["topics"][0]["title"] == "AI Agent 新闻"


def test_render_topics_markdown_includes_source_urls():
    topic = CandidateTopic(
        topic_id="search_topic_001",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=88,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[
            {
                "source_id": "github_search",
                "title": "example/agent",
                "url": "https://github.com/example/agent",
                "content_type": "repo",
                "source_weight": 95,
            }
        ],
        summary="GitHub 项目热度提升。",
        topic_score=90,
    )

    markdown = render_topics_markdown([topic], generated_at="2026-06-26T12:00:00+08:00")

    assert "# 关键词搜索话题推荐" in markdown
    assert "https://github.com/example/agent" in markdown