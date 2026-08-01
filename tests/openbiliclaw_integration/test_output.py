"""Tests for v2 output format (per-user file, no envelope, full body)."""

from __future__ import annotations

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import output


def _fake_rec(
    *,
    body: str = "body",
    confidence: float = 0.7,
    expression: str = "old reason",
    topic_label: str = "old label",
    platform: str = "weibo",
) -> Recommendation:
    item = DiscoveredContent(
        title="T",
        content_id="x",
        content_url="https://x",
        source_platform=platform,
        body_text=body,
        content_type="note",
        view_count=10,
        like_count=1,
        comment_count=0,
        source_rank=1,
    )
    return Recommendation(
        content=item,
        expression=expression,
        topic_label=topic_label,
        confidence=confidence,
        presented=False,
    )


def test_format_recommendation_drops_reason_and_topic_label() -> None:
    rec = _fake_rec()
    out = output.format_recommendation(rec, rank=1)
    assert "reason" not in out
    assert "topic_label" not in out
    assert "confidence" not in out


def test_format_recommendation_includes_full_body() -> None:
    long_body = "x" * 100_000
    rec = _fake_rec(body=long_body)
    out = output.format_recommendation(rec, rank=1, body_max_chars=50_000)
    assert len(out["body_text"]) == 50_000
    assert out["body_truncated"] is True
    assert out["body_text_length"] == 100_000


def test_format_recommendation_no_truncate_when_under_cap() -> None:
    rec = _fake_rec(body="short")
    out = output.format_recommendation(rec, rank=1, body_max_chars=50_000)
    assert out["body_text"] == "short"
    assert out["body_truncated"] is False


def test_format_recommendation_field_source_not_source_platform() -> None:
    rec = _fake_rec(platform="weibo")
    out = output.format_recommendation(rec, rank=1)
    assert out["source"] == "weibo"
    assert "source_platform" not in out


def test_format_user_file_returns_per_user_dict() -> None:
    recs = [_fake_rec(body="b1"), _fake_rec(body="b2")]
    out = output.format_user_file(
        user_id="u_001",
        track_1="AI",
        track_2="副业",
        persona="博主",
        recommendations=recs,
        body_max_chars=50000,
    )
    assert out["user_id"] == "u_001"
    assert out["input"] == {"track_1": "AI", "track_2": "副业", "persona": "博主"}
    assert "generated_at" in out
    assert len(out["recommendations"]) == 2


def test_format_user_failure_kept_for_partial_failures() -> None:
    out = output.format_user_failure(
        user_id="u_x",
        error_code="no_candidates",
        error_detail="empty",
    )
    assert out["user_id"] == "u_x"
    assert out["error"] == "no_candidates"