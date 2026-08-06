"""End-to-end last30days source pipeline test (v2.1.7 per-user dir)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation
from openpyxl import Workbook

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["user_id", "track_1", "track_2", "persona"])
    for row in rows:
        ws.append(row)
    wb.save(path)


def _fake_l30_articles() -> list[dict]:
    return [
        {
            "article_id": "weibo:l30_1",
            "title": "AI 微博热议",
            "url": "https://weibo.com/l30/1",
            "body_text": "微博正文",
            "summary": "微博正文摘要",
            "author": "weibo_user",
            "published_at": "",
            "tags": [],
            "heat": {"views": 5000, "likes": 100, "rank": 1},
            "platform": "weibo",
        },
        {
            "article_id": "zhihu:l30_1",
            "title": "AI 知乎讨论",
            "url": "https://zhihu.com/l30/1",
            "body_text": "知乎正文",
            "summary": "知乎摘要",
            "author": "zhihu_user",
            "published_at": "",
            "tags": [],
            "heat": {"voteups": 200, "num_comments": 30, "rank": 1},
            "platform": "zhihu",
        },
    ]


def test_end_to_end_last30days_source(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(xlsx, [["u_l30", "AI 大模型", "副业", "技术博主"]])
    out_dir = tmp_path / "recs"

    item = DiscoveredContent(
        title="AI 微博热议",
        content_id="weibo:l30_1",
        content_url="https://weibo.com/l30/1",
        source_platform="weibo",
        body_text="微博正文",
        content_type="note",
        view_count=5000,
        like_count=100,
        comment_count=0,
        source_rank=1,
    )
    fake_rec = Recommendation(
        content=item, expression="ignored", topic_label="ignored",
        confidence=0.88, presented=False,
    )

    with (
        patch.object(
            recommender, "_fetch_last30days_candidates_async",
            AsyncMock(return_value=_fake_l30_articles()),
        ),
        patch.object(
            recommender, "fetch_candidates",
            side_effect=AssertionError("V3 fetch_candidates must not run"),
        ),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng
        code = cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "last30days",
            "--last30days-cli-path", "/fake/last30days.py",
            "--max-parallel", "1",
            "--per-user-timeout", "30",
        ])

    assert code == 0
    user_dir = out_dir / "outputs" / "u_l30"
    assert user_dir.is_dir()
    inp = json.loads((user_dir / "input.json").read_text(encoding="utf-8"))
    assert inp["user_id"] == "u_l30"
    assert inp["track_1"] == "AI 大模型"
    articles = inp["articles"]
    assert any(article["title"] == "AI 微博热议" for article in articles)
    assert any(article["body_file"] == "text/01.txt" for article in articles)
    assert (user_dir / "summary.txt").exists()
    # body lives in text/NN.txt, not in input.json
    body_texts = {p.read_text(encoding="utf-8") for p in (user_dir / "text").iterdir()}
    assert "微博正文" in body_texts
