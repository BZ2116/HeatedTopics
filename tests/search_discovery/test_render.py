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


def test_render_topics_markdown_outputs_creator_reference_fields():
    topic = CandidateTopic(
        topic_id="t1",
        title="AI Agent 开源项目仍在快速更新",
        matched_keywords=["AI Agent", "MCP"],
        keyword_categories=["tech_project"],
        profile_match_score=90,
        freshness="ongoing",
        detail_level="high",
        risk_level="low",
        source_hits=[
            {
                "source_id": "github_search",
                "title": "example/agent-framework",
                "url": "https://github.com/example/agent-framework",
                "content_type": "repo",
                "source_weight": 100,
                "route_reason": "科技类创作者关注开源项目，GitHub 适合召回 repo。",
            }
        ],
        summary="多个开源项目结果显示 AI Agent 工具链仍在活跃更新。",
        topic_score=88,
    )

    markdown = render_topics_markdown([topic], generated_at="2026-06-29T12:00:00+08:00")

    assert "匹配原因" in markdown
    assert "关键信息" in markdown
    assert "创作角度" in markdown
    assert "证据来源" in markdown
    assert "可信度" in markdown
    assert "风险提示" in markdown
    assert "https://github.com/example/agent-framework" in markdown