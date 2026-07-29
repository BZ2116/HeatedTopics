"""Format recommendations into the JSON output schema."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from openbiliclaw.recommendation.engine import Recommendation


def _truncate(s: str, max_chars: int) -> str:
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[:max_chars]


def format_recommendation(
    rec: Recommendation,
    *,
    rank: int,
    body_preview_chars: int,
) -> dict[str, Any]:
    """Convert one Recommendation to its output dict shape."""
    item = rec.content
    return {
        "rank": rank,
        "title": item.title,
        "url": item.content_url,
        "source_platform": item.source_platform,
        "heat": {
            "view": int(item.view_count),
            "like": int(item.like_count),
            "comment": int(item.comment_count),
            "favorite": int(item.favorite_count),
            "share": int(item.share_count),
            "rank": int(item.source_rank),
        },
        "body_text_preview": _truncate(item.body_text or "", body_preview_chars),
        "body_text_length": len(item.body_text or ""),
        "topic_label": rec.topic_label or "",
        "reason": rec.expression or "",
        "confidence": float(rec.confidence),
        "published_at": item.published_at or "",
    }


def format_user_failure(
    *,
    user_id: str,
    error_code: str,
    error_detail: str,
) -> dict[str, Any]:
    """Format a failed user entry for the output JSON."""
    return {
        "user_id": user_id,
        "error": error_code,
        "error_detail": error_detail,
    }


def format_user_success_summary(
    user_id: str,
    display_name: str,
    interests_count: int,
    disliked_count: int,
    fetched: int,
    after_filter: int,
    considered: int,
    embedding_degraded: bool,
) -> dict[str, Any]:
    """Format the per-user envelope (recommendations added separately)."""
    return {
        "user_id": user_id,
        "display_name": display_name,
        "input_profile_summary": {
            "interests_count": interests_count,
            "disliked_count": disliked_count,
        },
        "pipeline": {
            "candidates_fetched": fetched,
            "candidates_after_filter": after_filter,
            "candidates_considered_by_engine": considered,
            "embedding_degraded": embedding_degraded,
        },
        "recommendations": [],
    }


def build_envelope(
    *,
    users: list[dict[str, Any]],
    llm_model: str,
    embedding_model: str,
    config_version: str,
) -> dict[str, Any]:
    """Build the top-level output JSON."""
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_version": config_version,
        "llm_model": llm_model,
        "embedding_model": embedding_model,
        "users": users,
    }
