import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.search_discovery.types import SearchResult


def read_recommendation_history(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_recommendation_history(path: Path, history: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mark_recent_recommendations(
    results: list[SearchResult],
    *,
    history: dict[str, dict[str, Any]],
    now: datetime,
    cooldown_days: int = 30,
) -> list[SearchResult]:
    marked: list[SearchResult] = []
    for result in results:
        history_row = history.get(result.url)
        metrics = dict(result.metrics)
        if history_row and _within_cooldown(str(history_row.get("recommended_at", "")), now, cooldown_days):
            metrics["recently_recommended"] = True
            metrics["last_recommended_at"] = str(history_row.get("recommended_at", ""))
        else:
            metrics["recently_recommended"] = False
        marked.append(SearchResult(**{**result.to_dict(), "metrics": metrics}))
    return marked


def update_recommendation_history(
    history: dict[str, dict[str, Any]],
    results: list[SearchResult],
    *,
    recommended_at: str,
) -> dict[str, dict[str, Any]]:
    updated = dict(history)
    for result in results:
        if not result.url or result.fetch_status != "ok":
            continue
        updated[result.url] = {
            "title": result.title,
            "recommended_at": recommended_at,
            "source_id": result.source_id,
        }
    return updated


def _within_cooldown(recommended_at: str, now: datetime, cooldown_days: int) -> bool:
    if not recommended_at:
        return False
    parsed = datetime.fromisoformat(recommended_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return now - parsed <= timedelta(days=cooldown_days)
