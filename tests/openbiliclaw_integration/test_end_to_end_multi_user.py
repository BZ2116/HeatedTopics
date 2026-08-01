"""End-to-end multi-user test verifying per-user/date isolation (v2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from openpyxl import Workbook
from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["user_id", "track_1", "track_2", "persona"])
    for row in rows:
        ws.append(row)
    wb.save(path)


def _fake_rec(user_id: str) -> Recommendation:
    item = DiscoveredContent(
        title=f"T-{user_id}",
        content_id=user_id,
        content_url=f"https://x.com/{user_id}",
        source_platform="juejin",
        body_text=f"body-{user_id}",
        content_type="note",
    )
    return Recommendation(
        content=item,
        expression=f"reason-{user_id}",
        topic_label=f"tp-{user_id}",
        confidence=0.7,
        presented=False,
    )


def test_end_to_end_three_users_independent_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(
        xlsx,
        [
            ["u_a", "x", "x2", "p_a"],
            ["u_b", "y", "y2", "p_b"],
            ["u_c", "z", "z2", "p_c"],
        ],
    )
    out_dir = tmp_path / "recs"
    article = {
        "article_id": "1", "title": "T", "url": "https://x.com/1",
        "body_text": "body", "author": "a",
        "heat": {"view": 1, "like": 1, "comment": 1, "rank": 1},
        "tags": [], "platform": "juejin",
    }
    engines: dict[str, MagicMock] = {}

    def factory(spec, **kwargs):
        eng = MagicMock()
        engines[spec.user_id] = eng
        eng.serve_external_candidates = AsyncMock(
            return_value=[_fake_rec(spec.user_id)]
        )
        return eng

    with (
        patch.object(recommender, "fetch_candidates", return_value=[article]),
        patch.object(recommender, "build_recommender", side_effect=factory),
    ):
        code = cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "v3-hotlist",
            "--max-parallel", "3",
        ])

    assert code == 0
    # Each user has its own directory tree
    for uid in ("u_a", "u_b", "u_c"):
        user_dir = out_dir / uid
        assert user_dir.is_dir(), f"missing user dir: {user_dir}"
        date_dirs = [d for d in user_dir.iterdir() if d.is_dir()]
        assert len(date_dirs) == 1
        target = date_dirs[0] / "recommendations.json"
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["user_id"] == uid
        assert data["recommendations"][0]["title"] == f"T-{uid}"
        assert "reason" not in data["recommendations"][0]
    assert len(engines) == 3