"""End-to-end one-user test with mocked engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def test_end_to_end_one_user_writes_correct_envelope(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    up = tmp_path / "users.json"
    up.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "u_security",
                        "display_name": "Sec",
                        "interests": [
                            {"name": "零信任", "category": "网安", "weight": 0.9}
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "recs.json"
    article = {
        "article_id": "1",
        "title": "T",
        "url": "https://x.com/1",
        "body_text": "body",
        "author": "a",
        "heat": {"view": 100, "like": 10, "comment": 2, "rank": 1},
        "tags": [],
        "platform": "juejin",
    }
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    item = DiscoveredContent(
        title="T",
        content_id="1",
        content_url="https://x.com/1",
        source_platform="juejin",
        body_text="body",
        content_type="note",
        view_count=100,
        like_count=10,
        comment_count=2,
        source_rank=1,
    )
    fake_rec = Recommendation(
        content=item,
        expression="matches your interest",
        topic_label="网安",
        confidence=0.85,
        presented=False,
    )
    with (
        patch.object(recommender, "fetch_candidates", return_value=[article]),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng
        code = cli.main(
            ["--users", str(up), "--output", str(out), "--max-parallel", "1"]
        )
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    rec = data["users"][0]["recommendations"][0]
    assert data["users"][0]["user_id"] == "u_security"
    assert rec["title"] == "T" and rec["heat"]["view"] == 100
    assert rec["reason"] == "matches your interest" and rec["topic_label"] == "网安"
    assert rec["body_text_preview"] == "body" and rec["body_text_length"] == 4
    assert data["llm_model"] == "MiniMax-M2.7"
