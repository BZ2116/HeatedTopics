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

    outputs = run_juejin_pipeline(
        profile_path=profile_path,
        output_dir=tmp_path / "out",
        fetched_at="2026-07-11T13:28:53+08:00",
        fetcher=fake_fetcher,
    )

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    matches = json.loads(outputs["matches"].read_text(encoding="utf-8"))
    report = outputs["report"].read_text(encoding="utf-8")

    assert len(hot_items) == 2
    assert len(matches) == 1
    assert matches[0]["item"]["title"] == "AI Agent workflow with MCP"
    assert matches[0]["match_terms"] == ["AI Agent", "MCP"]
    assert "# Juejin Hot Topics Report" in report
    assert "AI Agent workflow with MCP" in report
