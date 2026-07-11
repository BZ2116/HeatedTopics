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
    assert set(outputs) == {"article_texts", "hot_items", "report"}
    assert outputs["article_texts"] == run_dir / "article_texts"
    assert outputs["hot_items"].parent == run_dir
    assert outputs["report"].parent == run_dir
    assert outputs["hot_items"].name == "hot_items.json"
    assert outputs["report"].name == "report.md"

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    report = outputs["report"].read_text(encoding="utf-8")
    text_files = sorted(outputs["article_texts"].glob("*.txt"))

    assert len(hot_items) == 1
    assert hot_items[0]["item"]["title"] == "AI Agent workflow with MCP"
    assert hot_items[0]["match_terms"] == ["AI Agent", "MCP"]
    assert hot_items[0]["detail"]["fetch_status"] == "success"
    assert hot_items[0]["detail"]["extraction_method"] == "juejin_detail_api"
    assert hot_items[0]["detail"]["content_chars"] == len("Detailed MCP workflow content.")
    assert hot_items[0]["detail"]["txt_path"] == "article_texts/001_AI Agent workflow with MCP.txt"
    assert len(text_files) == 1
    assert text_files[0].name == "001_AI Agent workflow with MCP.txt"
    text = text_files[0].read_text(encoding="utf-8")
    assert "Title: AI Agent workflow with MCP" in text
    assert "Platform: juejin" in text
    assert "Detailed MCP workflow content." in text
    assert "# Juejin Hot Topics Report" in report
    assert "AI Agent workflow with MCP" in report
