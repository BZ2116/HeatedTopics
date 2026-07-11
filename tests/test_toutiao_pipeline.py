import json
from pathlib import Path

from heated_topics_v3.pipeline import run_toutiao_pipeline


def test_run_toutiao_pipeline_writes_dataset_and_report(tmp_path: Path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech", "ai"],
                "audience": ["developers"],
                "content_modes": ["analysis"],
                "preferred_platforms": ["toutiao"],
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
                "status": "success",
                "data": [
                    {
                        "ClusterId": "1",
                        "Title": "AI Agent product launches",
                        "Url": "https://www.toutiao.com/article/1",
                        "HotValue": "1000",
                        "QueryWord": "AI Agent product launches",
                        "InterestCategory": ["technology"],
                    },
                    {
                        "ClusterId": "2",
                        "Title": "Weather headline",
                        "Url": "https://www.toutiao.com/trending/2/",
                        "HotValue": "500",
                        "QueryWord": "Weather headline",
                    },
                ],
            }
        )

    def fake_detail_fetcher(url: str, timeout_seconds: int) -> str:
        return """
        <html>
          <body>
            <article>
              <h1>AI Agent product launches</h1>
              <p>Detailed Toutiao body.</p>
            </article>
          </body>
        </html>
        """

    outputs = run_toutiao_pipeline(
        profile_path=profile_path,
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-11T14:50:00+08:00",
        fetcher=fake_fetcher,
        detail_fetcher=fake_detail_fetcher,
    )

    run_dir = tmp_path / "outputs" / "tech_ai_creator" / "toutiao" / "run_20260711_145000"
    assert set(outputs) == {"profile", "queries", "hot_items", "matches", "item_details", "report"}
    assert all(path.parent == run_dir for path in outputs.values())

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    matches = json.loads(outputs["matches"].read_text(encoding="utf-8"))
    item_details = json.loads(outputs["item_details"].read_text(encoding="utf-8"))
    report = outputs["report"].read_text(encoding="utf-8")

    assert len(hot_items) == 2
    assert len(matches) == 1
    assert matches[0]["item"]["title"] == "AI Agent product launches"
    assert matches[0]["match_terms"] == ["AI Agent"]
    assert item_details[0]["content"] == "AI Agent product launches\nDetailed Toutiao body."
    assert "# Toutiao Hot Topics Report" in report
    assert "AI Agent product launches" in report
