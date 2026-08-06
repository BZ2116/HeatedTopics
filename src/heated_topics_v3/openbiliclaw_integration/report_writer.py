"""Write per-user reports with one overall summary and separate article bodies."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heated_topics_v3.clock import SHANGHAI

if TYPE_CHECKING:
    from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec

logger = logging.getLogger(__name__)


def write_user_report(
    out_dir: Path,
    *,
    user_id: str,
    track_1: str,
    track_2: str,
    persona: str,
    recommendations: list[dict[str, Any]],
    summary: str | None,
    body_max_chars: int = 50_000,
) -> Path:
    """Write input.json, summary.txt, and text/<rank>.txt for one user."""
    out_dir.mkdir(parents=True, exist_ok=True)
    text_dir = out_dir / "text"
    text_dir.mkdir(exist_ok=True)

    articles: list[dict[str, Any]] = []
    for item in recommendations:
        rank = int(item["rank"])
        body_file = f"text/{rank:02d}.txt"
        body = (item.get("body_text", "") or "")[:body_max_chars]
        (out_dir / body_file).write_text(body, encoding="utf-8")
        articles.append(
            {
                "rank": rank,
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "platform": item.get("source", ""),
                "query": item.get("search_query", "") or "",
                "heat": item.get("heat", {}) or {},
                "published_at": item.get("published_at", "") or "",
                "body_file": body_file,
            }
        )

    (out_dir / "summary.txt").write_text(summary or "", encoding="utf-8")
    payload = {
        "user_id": user_id,
        "track_1": track_1,
        "track_2": track_2,
        "persona": persona,
        "generated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "recommendation_count": len(recommendations),
        "summary_file": "summary.txt",
        "articles": articles,
    }
    (out_dir / "input.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("wrote report for %s: %d recs -> %s", user_id, len(articles), out_dir)
    return out_dir


def write_inputs_registry(out_dir: Path, specs: list["UserSpec"]) -> Path:
    """Write inputs/users.json keyed by caller-supplied user IDs."""
    inputs_dir = out_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        spec.user_id: {
            "track_1": spec.track_1,
            "track_2": spec.track_2,
            "persona": spec.persona,
        }
        for spec in specs
    }
    registry_path = inputs_dir / "users.json"
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("wrote inputs registry with %d users -> %s", len(registry), registry_path)
    return registry_path


__all__ = ["write_user_report", "write_inputs_registry"]
