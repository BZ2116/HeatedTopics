import json

from src.search_discovery.cli import run_discovery_command


def test_run_discovery_command_writes_isolated_outputs(tmp_path):
    profile_path = tmp_path / "config/search_discovery/creator_profiles/tech_ai_creator.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "track_tags": ["AI"],
                "custom_keywords": ["AI Agent"],
                "content_modes": ["教程实践"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    counts = run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=True)

    assert counts["search_results_count"] > 0
    assert (tmp_path / "data/search_discovery/raw/search_results.jsonl").exists()
    assert (tmp_path / "data/search_discovery/processed/search_topic_index.json").exists()
    assert (tmp_path / "reports/search_discovery/search_topic_recommendations.md").exists()
    assert not (tmp_path / "data/raw/dailyhot_records.json").exists()