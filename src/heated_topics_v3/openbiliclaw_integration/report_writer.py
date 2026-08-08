"""Write per-user reports with one overall summary and separate article bodies."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heated_topics_v3.clock import SHANGHAI

if TYPE_CHECKING:
    from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec

logger = logging.getLogger(__name__)


def _article_filename(rank: int, title: str) -> str:
    # Keep filenames readable while preventing platform/path characters.
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", title).strip("_")[:40]
    return f"{rank:02d}_{slug or 'article'}.json"


def write_user_report(
    out_dir: Path,
    *,
    user_id: str,
    track_1: str,
    track_2: str,
    persona: str,
    recommendations: list[dict[str, Any]],
    searched_articles: list[dict[str, Any]] | None = None,
    summary: str | None,
    body_max_chars: int = 50_000,
) -> Path:
    """Write one user directory and one JSON artifact per recommendation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    text_dir = out_dir / "text"
    text_dir.mkdir(exist_ok=True)
    searched_dir = out_dir / "search"
    searched_dir.mkdir(exist_ok=True)
    recommended_dir = out_dir / "recommended"
    recommended_dir.mkdir(exist_ok=True)

    for i, item in enumerate(searched_articles or [], start=1):
        filename = _article_filename(i, str(item.get("title", "")))
        bucket = "search" if item.get("search_query") else "hot"
        platform = re.sub(r"[^0-9A-Za-z_-]+", "_", str(item.get("platform") or "unknown"))
        target_dir = searched_dir / bucket / platform
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / filename).write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    articles: list[dict[str, Any]] = []
    for item in recommendations:
        rank = int(item["rank"])
        body_file = f"text/{rank:02d}.txt"
        article_file = _article_filename(rank, str(item.get("title", "")))
        full_body = item.get("body_text_full") or item.get("body_text", "") or ""
        body = full_body[:body_max_chars]
        (out_dir / body_file).write_text(body, encoding="utf-8")
        article = {
                "fetched_at": item.get("fetched_at") or item.get("generated_at") or datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                "rank": rank,
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "platform": item.get("source", ""),
                "author": item.get("author", "") or "",
                "body": full_body,
                "query": item.get("search_query", "") or "",
                "published_at": item.get("published_at", "") or "",
                "body_file": body_file,
            }
        heat = item.get("heat", {}) or {}
        if heat:
            metrics = {k: int(heat[k]) for k in ("view", "like", "comment") if heat.get(k) is not None and int(heat[k]) > 0}
            if metrics:
                article["metrics"] = metrics
        (out_dir / article_file).write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
        (recommended_dir / article_file).write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
        platform_dir = re.sub(r"[^0-9A-Za-z_-]+", "_", str(item.get("source") or "unknown"))
        (recommended_dir / platform_dir).mkdir(parents=True, exist_ok=True)
        (recommended_dir / platform_dir / article_file).write_text(
            json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Keep the legacy index shape stable; the complete record lives in
        # the per-article JSON file written above.
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
