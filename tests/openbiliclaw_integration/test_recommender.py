"""Tests for recommender orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import recommender


def _mock_article(
    article_id: str = "1", title: str = "T", platform: str = "juejin"
) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": title,
        "url": f"https://{platform}.com/{article_id}",
        "body_text": "body",
        "author": "a",
        "heat": {"view": 100, "like": 10, "comment": 1, "rank": 1},
        "tags": [],
    }


def _mock_recommendation(
    title: str = "T", topic: str = "tp", reason: str = "r", confidence: float = 0.8
) -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id="1",
        content_url="https://x.com/1",
        source_platform="juejin",
        body_text="body",
        content_type="note",
    )
    return Recommendation(
        content=item,
        expression=reason,
        topic_label=topic,
        confidence=confidence,
        presented=False,
    )


def test_run_one_user_returns_recommendations(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )

    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
        )
    assert result["user_id"] == spec.user_id
    assert "recommendations" in result
    assert len(result["recommendations"]) == 1
    assert result["pipeline"]["candidates_fetched"] == 1


def test_run_one_user_handles_no_candidates(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(return_value=[])

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=[]),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)
    assert "error" in result
    assert result["error"] == "no_candidates"


def test_run_one_user_timeout_returns_error(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(side_effect=TimeoutError)

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(
            spec, data_dir=tmp_path / "runtime", limit=5, per_user_timeout=0.1
        )
    assert "error" in result


def test_run_one_user_isolated_engine_per_user(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    engines = []

    def fake_build_recommender(spec, data_dir, **kwargs):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[_mock_recommendation()])
        engines.append((spec.user_id, data_dir))
        return eng

    with (
        patch.object(
            recommender, "build_recommender", side_effect=fake_build_recommender
        ),
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
    ):
        for spec in recommender.load_users(users_p):
            recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)
    assert len(engines) == 3
    # Each user gets a distinct data_dir
    assert len({d for _, d in engines}) == 3


def test_run_one_user_propagates_rank_to_confidence(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    """End-to-end-ish: fetch_candidates returns articles with various ranks,
    the engine mirrors real OpenBiliClaw behavior (sets ``confidence`` from
    ``content.relevance_score``), and the output dict reflects the non-zero
    confidence. Regression for the ``confidence: 0.0`` bug where
    candidate_adapter never set relevance_score.
    """
    from heated_topics_v3.openbiliclaw_integration import candidate_adapter

    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    articles = [
        {**_mock_article(article_id=f"a{i}"), "heat": {"rank": i}}
        for i in (1, 2, 5, 10)
    ]

    captured: list[DiscoveredContent] = []

    async def fake_serve(profile, candidates, **kwargs):
        captured.extend(candidates)
        # Mirror what the real engine does:
        # confidence = item.relevance_score
        return [
            Recommendation(
                content=item,
                expression=f"rec for {item.content_id}",
                topic_label="t",
                confidence=item.relevance_score,
                presented=False,
            )
            for item in candidates
        ]

    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(side_effect=fake_serve)

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=articles),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)

    # Adapter received the rank and mapped it to relevance_score.
    assert len(captured) == 4
    by_rank = {item.source_rank: item for item in captured}
    assert by_rank[1].relevance_score == 1.0
    assert by_rank[2].relevance_score == 0.5
    assert by_rank[5].relevance_score == 0.2
    assert by_rank[10].relevance_score == 0.1

    # Confidence on the output reflects the rank-derived relevance_score.
    confidences = [r["confidence"] for r in result["recommendations"]]
    assert all(c > 0.0 for c in confidences), confidences
    assert max(confidences) == pytest.approx(1.0)


def test_build_provider_dispatches_dailyhot_route() -> None:
    """``dailyhot:<route>`` resolves to DailyHotApiProvider(route)."""
    from heated_topics_v3.providers.dailyhot import DailyHotApiProvider

    built = recommender._build_provider("dailyhot:36kr")
    assert built is not None
    provider, client = built
    assert isinstance(provider, DailyHotApiProvider)
    assert provider.platform == "36kr"
    client.close()


def test_build_provider_returns_none_for_unknown() -> None:
    assert recommender._build_provider("totally_made_up_platform") is None
