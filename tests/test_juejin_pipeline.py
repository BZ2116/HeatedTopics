import json
from pathlib import Path

from heated_topics_v3.pipeline import run_juejin_pipeline


def test_run_juejin_pipeline_writes_dataset_and_report(tmp_path: Path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech", "ai"],
                "audience": ["developers"],
                "content_modes": ["tutorial", "analysis"],
                "preferred_platforms": ["juejin"],
                "core_keywords": ["AI Agent", "MCP"],
                "entity_keywords": ["Claude Code"],
                "excluded_keywords": ["unverified rumor"],
            }
        ),
        encoding="utf-8",
    )

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        return json.dumps(
            {
                "err_no": 0,
                "data": [
                    {
                        "content": {
                            "content_id": "1",
                            "title": "AI Agent workflow with MCP",
                            "brief": "A practical developer article.",
                            "category_id": "tech",
                        },
                        "content_counter": {"hot_rank": 500, "view": 1000},
                    },
                    {
                        "content": {
                            "content_id": "2",
                            "title": "CSS layout notes",
                            "brief": "",
                            "category_id": "tech",
                        },
                        "content_counter": {"hot_rank": 300},
                    },
                ],
            }
        )

    def fake_detail_fetcher(url: str, timeout_seconds: int, body: dict[str, str] | None = None) -> str:
        assert body == {"article_id": "1"}
        return json.dumps(
            {
                "err_no": 0,
                "data": {
                    "article_info": {
                        "title": "AI Agent workflow with MCP",
                        "brief_content": "A practical developer article.",
                        "mark_content": "Detailed MCP workflow content.",
                    },
                    "author_user_info": {"user_name": "Author"},
                    "tags": [{"tag_name": "AI Agent"}, {"tag_name": "MCP"}],
                },
            }
        )

    outputs = run_juejin_pipeline(
        profile_path=profile_path,
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-11T13:28:53+08:00",
        fetcher=fake_fetcher,
        detail_fetcher=fake_detail_fetcher,
    )

    run_dir = tmp_path / "outputs" / "tech_ai_creator" / "juejin" / "run_20260711_132853"
    assert set(outputs) == {"profile", "queries", "hot_items", "matches", "item_details", "report"}
    assert all(path.parent == run_dir for path in outputs.values())
    assert outputs["profile"].name == "profile.json"
    assert outputs["queries"].name == "queries.json"
    assert outputs["hot_items"].name == "hot_items.json"
    assert outputs["matches"].name == "matches.json"
    assert outputs["item_details"].name == "item_details.json"
    assert outputs["report"].name == "report.md"

    profile = json.loads(outputs["profile"].read_text(encoding="utf-8"))
    queries = json.loads(outputs["queries"].read_text(encoding="utf-8"))
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    matches = json.loads(outputs["matches"].read_text(encoding="utf-8"))
    item_details = json.loads(outputs["item_details"].read_text(encoding="utf-8"))
    report = outputs["report"].read_text(encoding="utf-8")

    assert profile["profile_id"] == "tech_ai_creator"
    assert queries[0]["profile_id"] == "tech_ai_creator"
    assert len(hot_items) == 2
    assert len(matches) == 1
    assert matches[0]["item"]["title"] == "AI Agent workflow with MCP"
    assert matches[0]["match_terms"] == ["AI Agent", "MCP"]
    assert item_details[0]["item_id"] == "juejin_1"
    assert item_details[0]["content"] == "Detailed MCP workflow content."
    assert item_details[0]["extraction_method"] == "juejin_detail_api"
    assert "# Juejin Hot Topics Report" in report
    assert "AI Agent workflow with MCP" in report
