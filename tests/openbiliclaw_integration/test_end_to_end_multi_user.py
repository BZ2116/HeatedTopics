"""End-to-end multi-user test verifying per-user isolation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation
from heated_topics_v3.openbiliclaw_integration import cli, recommender


def _fake_rec(user_id: str) -> Recommendation:
    item = DiscoveredContent(title=f"T-{user_id}", content_id=user_id, content_url=f"https://x.com/{user_id}", source_platform="juejin", body_text=f"body-{user_id}", content_type="note")
    return Recommendation(content=item, expression=f"reason-{user_id}", topic_label=f"tp-{user_id}", confidence=0.7, presented=False)


def test_end_to_end_three_users_independent_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    users = {"users": [{"user_id": uid, "interests": [{"name": value, "category": value, "weight": 0.5}]} for uid, value in (("u_a", "x"), ("u_b", "y"), ("u_c", "z"))]}
    up = tmp_path / "users.json"; up.write_text(json.dumps(users), encoding="utf-8")
    out = tmp_path / "recs.json"
    article = {"article_id": "1", "title": "T", "url": "https://x.com/1", "body_text": "body", "author": "a", "heat": {"view": 1, "like": 1, "comment": 1, "rank": 1}, "tags": [], "platform": "juejin"}
    engines = {}
    def factory(spec, **kwargs):
        eng = MagicMock(); engines[spec.user_id] = eng; eng.serve_external_candidates = AsyncMock(return_value=[_fake_rec(spec.user_id)]); return eng
    with patch.object(recommender, "fetch_candidates", return_value=[article]), patch.object(recommender, "build_recommender", side_effect=factory):
        code = cli.main(["--users", str(up), "--output", str(out), "--max-parallel", "3"])
    assert code == 0
    by_user = {u["user_id"]: u for u in json.loads(out.read_text())["users"]}
    assert set(by_user) == {"u_a", "u_b", "u_c"}
    for uid, user in by_user.items():
        assert user["recommendations"][0]["title"] == f"T-{uid}"
        assert user["recommendations"][0]["topic_label"] == f"tp-{uid}"
    assert len(engines) == 3
