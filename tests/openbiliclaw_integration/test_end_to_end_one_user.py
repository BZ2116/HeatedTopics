"""End-to-end one-user test (v2: per-user/date file output)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from openpyxl import Workbook

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["user_id", "track_1", "track_2", "persona"])
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_end_to_end_one_user_writes_per_user_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(xlsx, [["u_001", "AI", "副业", "博主"]])
    out_dir = tmp_path / "recs"

    article = {
        "article_id": "1", "title": "T", "url": "https://x.com/1",
        "body_text": "完整正文内容超过十个字", "author": "a",
        "heat": {"rank": 1}, "tags": [], "platform": "juejin",
    }
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    item = DiscoveredContent(
        title="T", content_id="1", content_url="https://x.com/1",
        source_platform="juejin", body_text="完整正文内容超过十个字",
        content_type="note", view_count=100, like_count=10,
        comment_count=2, source_rank=1,
    )
    fake_rec = Recommendation(
        content=item, expression="ignored", topic_label="ignored",
        confidence=0.85, presented=False,
    )

    with (
        patch.object(recommender, "fetch_candidates", return_value=[article]),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng
        code = cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "v3-hotlist",
            "--max-parallel", "1",
        ])

    assert code == 0
    user_dir = out_dir / "u_001"
    date_dirs = [d for d in user_dir.iterdir() if d.is_dir()]
    assert len(date_dirs) == 1
    target = date_dirs[0] / "recommendations.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["user_id"] == "u_001"
    assert data["input"]["track_1"] == "AI"
    assert data["recommendations"][0]["title"] == "T"
    assert data["recommendations"][0]["source"] == "juejin"
    assert data["recommendations"][0]["body_text"] == "完整正文内容超过十个字"
    assert "reason" not in data["recommendations"][0]
    assert "topic_label" not in data["recommendations"][0]
    assert "confidence" not in data["recommendations"][0]


def test_end_to_end_one_user_writes_keyword_cache(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify CLI triggers LLM keyword extraction + writes per-user cache."""
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(xlsx, [
        ["wh_user_01", "文化生活", "非遗与民俗", "研究地方习俗、节气、非遗和老手艺"],
    ])
    out_dir = tmp_path / "recs"

    article = {
        "article_id": "1", "title": "T", "url": "https://x.com/1",
        "body_text": "正文足够长超过十个字", "author": "a",
        "heat": {"rank": 1}, "tags": [], "platform": "juejin",
    }
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    item = DiscoveredContent(
        title="T", content_id="1", content_url="https://x.com/1",
        source_platform="juejin", body_text="正文足够长超过十个字",
        content_type="note",
    )
    fake_rec = Recommendation(
        content=item, expression="x", topic_label="t",
        confidence=0.7, presented=False,
    )

    llm_called = {"n": 0}

    async def fake_extract(spec, llm, *, n=3, timeout=30.0):
        llm_called["n"] += 1
        return ["非遗手工艺", "传统节气", "老字号"]

    # Patch the LLM call inside extract_or_load so the real cache-write
    # path runs and the file actually appears on disk.
    with (
        patch.object(
            recommender.keyword_extractor, "_extract_via_llm",
            side_effect=fake_extract,
        ),
        patch.object(recommender, "fetch_candidates", return_value=[article]),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng
        code = cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "v3-hotlist",
            "--max-parallel", "1",
        ])

    assert code == 0
    assert llm_called["n"] == 1

    cache_file = out_dir / "_keyword_cache" / "wh_user_01" / "keyword_cache.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["keywords"] == ["非遗手工艺", "传统节气", "老字号"]
    assert payload["track_1"] == "文化生活"
    assert payload["track_2"] == "非遗与民俗"
    assert len(payload["spec_hash"]) == 64  # sha256 hex


def test_end_to_end_no_keyword_extraction_skips_llm(
    tmp_path: Path, monkeypatch
) -> None:
    """With --no-keyword-extraction, LLM is not called and no cache is written."""
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(xlsx, [["u_off", "AI", "副业", "博主"]])
    out_dir = tmp_path / "recs"

    article = {
        "article_id": "1", "title": "T", "url": "https://x.com/1",
        "body_text": "正文足够长超过十个字", "author": "a",
        "heat": {"rank": 1}, "tags": [], "platform": "juejin",
    }
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    item = DiscoveredContent(
        title="T", content_id="1", content_url="https://x.com/1",
        source_platform="juejin", body_text="正文足够长超过十个字",
        content_type="note",
    )
    fake_rec = Recommendation(
        content=item, expression="x", topic_label="t",
        confidence=0.7, presented=False,
    )

    async def should_not_call(*args, **kwargs):
        raise AssertionError("LLM should not be called when extraction disabled")

    with (
        patch.object(
            recommender, "extract_or_load", side_effect=should_not_call,
        ),
        patch.object(recommender, "fetch_candidates", return_value=[article]),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng
        code = cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "v3-hotlist",
            "--no-keyword-extraction",
            "--max-parallel", "1",
        ])

    assert code == 0
    cache_file = out_dir / "_keyword_cache" / "u_off" / "keyword_cache.json"
    assert not cache_file.exists()