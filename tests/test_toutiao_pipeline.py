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
        if "so.toutiao.com/search/" in url:
            return json.dumps(
                {
                    "keyword": "AI智能体",
                    "count": 1,
                    "dom": """
                    <div class="result-card">
                      <a href="https://www.toutiao.com/article/1">AI Agent product launches</a>
                      <div>阅读 12万 评论 345</div>
                      <p>Detailed search summary.</p>
                    </div>
                    """,
                }
            )
        return json.dumps(
            {
                "status": "success",
                "data": [
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
    assert set(outputs) == {"article_texts", "hot_items", "report"}
    assert outputs["article_texts"] == run_dir / "article_texts"
    assert outputs["hot_items"].parent == run_dir
    assert outputs["report"].parent == run_dir

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    report = outputs["report"].read_text(encoding="utf-8")
    text_files = sorted(outputs["article_texts"].glob("*.txt"))

    assert len(hot_items) == 1
    assert hot_items[0]["item"]["title"] == "AI Agent product launches"
    assert "AI Agent" in hot_items[0]["match_terms"]
    assert hot_items[0]["detail"]["txt_path"] == "article_texts/001_AI Agent product launches.txt"
    assert len(text_files) == 1
    assert text_files[0].name == "001_AI Agent product launches.txt"
    text = text_files[0].read_text(encoding="utf-8")
    assert "Title: AI Agent product launches" in text
    assert "Platform: toutiao" in text
    assert "AI Agent product launches\nDetailed Toutiao body." in text
    assert "# Toutiao Hot Topics Report" in report
    assert "AI Agent product launches" in report
    assert "search_result" in report
    assert "search_engagement" in report or "weak" in report or "hot_value" in report
