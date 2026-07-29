"""Tests for output module."""

from __future__ import annotations

from typing import Any

import pytest

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import output


def _make_recommendation(
    title: str = "T",
    url: str = "https://x.com/1",
    body_text: str = "body",
    view: int = 100,
    like: int = 10,
    comment: int = 2,
    rank: int = 1,
    topic_label: str = "topic",
    reason: str = "reason",
    confidence: float = 0.8,
) -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id="1",
        content_url=url,
        source_platform="juejin",
        body_text=body_text,
        content_type="note",
        view_count=view,
        like_count=like,
        comment_count=comment,
        source_rank=rank,
    )
    return Recommendation(
        content=item,
        expression=reason,
        topic_label=topic_label,
        confidence=confidence,
        presented=False,
    )


def test_format_recommendation_includes_all_fields() -> None:
    rec = _make_recommendation()
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["rank"] == 1
    assert d["title"] == "T"
    assert d["url"] == "https://x.com/1"
    assert d["source_platform"] == "juejin"
    assert d["heat"]["view"] == 100
    assert d["heat"]["like"] == 10
    assert d["heat"]["comment"] == 2
    assert d["heat"]["rank"] == 1
    assert d["topic_label"] == "topic"
    assert d["reason"] == "reason"
    assert d["confidence"] == pytest.approx(0.8)
    assert d["body_text_preview"] == "body"


def test_body_text_truncation_at_boundary() -> None:
    long = "x" * 1500
    rec = _make_recommendation(body_text=long)
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert len(d["body_text_preview"]) == 800
    assert d["body_text_length"] == 1500


def test_body_text_truncation_under_limit() -> None:
    rec = _make_recommendation(body_text="hello")
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["body_text_preview"] == "hello"
    assert d["body_text_length"] == 5


def test_body_text_truncation_exactly_at_limit() -> None:
    rec = _make_recommendation(body_text="x" * 800)
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["body_text_preview"] == "x" * 800
    assert d["body_text_length"] == 800


def test_format_recommendation_handles_missing_optional_fields() -> None:
    item = DiscoveredContent(
        title="t",
        content_id="1",
        content_url="u",
        source_platform="juejin",
    )
    rec = Recommendation(content=item, expression="", topic_label="", confidence=0.0, presented=False)
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["body_text_preview"] == ""
    assert d["body_text_length"] == 0
    assert d["heat"]["view"] == 0


def test_format_user_failure() -> None:
    d = output.format_user_failure(
        user_id="u_x",
        error_code="no_candidates",
        error_detail="all providers failed",
    )
    assert d["user_id"] == "u_x"
    assert d["error"] == "no_candidates"
    assert d["error_detail"] == "all providers failed"


def test_format_user_success_summary() -> None:
    d = output.format_user_success_summary(
        user_id="u_x",
        display_name="X",
        interests_count=2,
        disliked_count=1,
        fetched=100,
        after_filter=80,
        considered=80,
        embedding_degraded=False,
    )
    assert d["user_id"] == "u_x"
    assert d["display_name"] == "X"
    assert d["input_profile_summary"]["interests_count"] == 2
    assert d["pipeline"]["candidates_fetched"] == 100
    assert d["pipeline"]["candidates_considered_by_engine"] == 80
    assert d["pipeline"]["embedding_degraded"] is False


def test_full_envelope() -> None:
    rec = _make_recommendation()
    user = output.format_user_success_summary(
        "u_x", "X", 1, 0, 10, 10, 10, False
    )
    user["recommendations"] = [
        output.format_recommendation(rec, rank=1, body_preview_chars=800)
    ]
    env = output.build_envelope(
        users=[user],
        llm_model="MiniMax-M2.7",
        embedding_model="bge-m3",
        config_version="0.3.186+mur.1",
    )
    assert "generated_at" in env
    assert env["llm_model"] == "MiniMax-M2.7"
    assert env["config_version"] == "0.3.186+mur.1"
    assert len(env["users"]) == 1
