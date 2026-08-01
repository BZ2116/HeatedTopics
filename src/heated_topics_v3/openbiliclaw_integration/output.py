"""Format recommendations into v2 JSON shape.

Per-user file schema (CLI writes one per user_id per date):

    {
      "user_id": "u_001",
      "input": {"track_1": ..., "track_2": ..., "persona": ...},
      "generated_at": "2026-08-01T12:34:56+08:00",
      "recommendations": [
        {
          "rank": 1, "title": "...", "url": "...",
          "source": "weibo",
          "heat": {"view":..., "like":..., "comment":..., "favorite":..., "share":..., "rank":...},
          "body_text": "完整正文",
          "body_text_length": 1234,
          "body_truncated": false,
          "published_at": "..."
        }
      ]
    }

v2 drops reason/topic_label/confidence (创作者要素材不要文案); body_text
取代 v1 的 body_text_preview（保留完整正文，默认 50000 字封顶）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.clock import SHANGHAI


def format_recommendation(
    rec: Recommendation,
    *,
    rank: int,
    body_max_chars: int = 50_000,
) -> dict[str, Any]:
    """Convert one Recommendation to its output dict (v2 schema)."""
    item = rec.content
    full_body = item.body_text or ""
    truncated = len(full_body) > body_max_chars
    body_text = full_body[:body_max_chars] if truncated else full_body
    return {
        "rank": rank,
        "title": item.title,
        "url": item.content_url,
        "source": item.source_platform,
        "heat": {
            "view": int(item.view_count),
            "like": int(item.like_count),
            "comment": int(item.comment_count),
            "favorite": int(item.favorite_count),
            "share": int(item.share_count),
            "rank": int(item.source_rank),
        },
        "body_text": body_text,
        "body_text_length": len(full_body),
        "body_truncated": truncated,
        "published_at": item.published_at or "",
    }


def format_user_file(
    *,
    user_id: str,
    track_1: str,
    track_2: str,
    persona: str,
    recommendations: list[Recommendation],
    body_max_chars: int = 50_000,
) -> dict[str, Any]:
    """Build the JSON payload for one user's recommendations file."""
    return {
        "user_id": user_id,
        "input": {
            "track_1": track_1,
            "track_2": track_2,
            "persona": persona,
        },
        "generated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "recommendations": [
            format_recommendation(r, rank=i + 1, body_max_chars=body_max_chars)
            for i, r in enumerate(recommendations)
        ],
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