"""Daily hot board cache.

Stores `cache/hot_board/{YYYY-MM-DD}.json` (UTC+8 day). All pipeline runs read
the cache; only first-of-day writes. Falls back to yesterday's snapshot when
today's is missing or fetch fails.
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from heated_topics_v3.contracts import HotBoardSnapshot, HotItem
from heated_topics_v3.providers.toutiao import (
    parse_toutiao_hot_board_response,
)


DEFAULT_HOT_BOARD_SUBDIR = "hot_board"
DEFAULT_SOURCE_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"


def utc8_today() -> str:
    """Current date in UTC+8 as 'YYYY-MM-DD'."""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def utc8_day_offset(date_str: str, *, days: int) -> str:
    """Return YYYY-MM-DD offset by N days (negative for previous days)."""
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def hot_board_cache_path(cache_root: str | Path, date: str) -> Path:
    return Path(cache_root) / DEFAULT_HOT_BOARD_SUBDIR / f"{date}.json"


def load_hot_board_snapshot(
    cache_root: str | Path, date: str,
) -> HotBoardSnapshot | None:
    """Read snapshot from cache if present and valid; None otherwise."""
    path = hot_board_cache_path(cache_root, date)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("date") != date:
        return None
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return None
    items = _hydrate_items(raw_items, payload.get("fetched_at", ""))
    return HotBoardSnapshot(
        date=date,
        fetched_at=str(payload.get("fetched_at", "")),
        items=tuple(items),
    )


def save_hot_board_snapshot(
    cache_root: str | Path,
    snapshot: HotBoardSnapshot,
    *,
    source_url: str = DEFAULT_SOURCE_URL,
) -> Path:
    """Write snapshot to cache atomically (tempfile + Path.replace)."""
    path = hot_board_cache_path(cache_root, snapshot.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": snapshot.date,
        "fetched_at": snapshot.fetched_at,
        "source_url": source_url,
        "items": _serialize_items(snapshot.items),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".hot_board_", suffix=".json", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def get_or_fetch_hot_board(
    cache_root: str | Path,
    date: str,
    *,
    fetcher: Callable[[str, int], str] | None = None,
    force_refresh: bool = False,
    allow_yesterday_fallback: bool = True,
    timeout_seconds: int = 20,
    source_url: str = DEFAULT_SOURCE_URL,
) -> tuple[HotBoardSnapshot, str]:
    """Return (snapshot, source) where source ∈ {cache, fresh, fallback_yesterday}.

    Raises RuntimeError if today and yesterday both fail.
    """
    if not force_refresh:
        cached = load_hot_board_snapshot(cache_root, date)
        if cached is not None and cached.items:
            return cached, "cache"

    fetched_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    items: list[HotItem] = []
    if fetcher is not None:
        try:
            response = fetcher(source_url, timeout_seconds)
            items = parse_toutiao_hot_board_response(response, fetched_at=fetched_at)
        except Exception:
            items = []

    if items:
        snapshot = HotBoardSnapshot(date=date, fetched_at=fetched_at, items=tuple(items))
        try:
            save_hot_board_snapshot(cache_root, snapshot, source_url=source_url)
        except OSError:
            pass
        return snapshot, "fresh"

    if allow_yesterday_fallback:
        yesterday = utc8_day_offset(date, days=-1)
        y_snapshot = load_hot_board_snapshot(cache_root, yesterday)
        if y_snapshot is not None and y_snapshot.items:
            return y_snapshot, "fallback_yesterday"

    raise RuntimeError(
        f"hot board unavailable for {date} (and no yesterday fallback found)"
    )


def _serialize_items(items: tuple[HotItem, ...]) -> list[dict]:
    serialized: list[dict] = []
    for item in items:
        serialized.append(
            {
                "item_id": item.item_id,
                "platform": item.platform,
                "item_type": item.item_type,
                "title": item.title,
                "url": item.url,
                "rank": item.rank,
                "heat": {
                    "value": item.heat.value,
                    "label": item.heat.label,
                    "metric_name": item.heat.metric_name,
                    "metrics": dict(item.heat.metrics),
                },
                "summary": item.summary,
                "category": item.category,
                "matched_query_ids": list(item.matched_query_ids),
                "fetched_at": item.fetched_at,
                "fetch_status": item.fetch_status,
                "raw_payload": dict(item.raw_payload),
            }
        )
    return serialized


def _hydrate_items(
    raw_items: list[dict], default_fetched_at: str,
) -> list[HotItem]:
    from heated_topics_v3.contracts import HeatMetrics

    hydrated: list[HotItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        heat_raw = entry.get("heat") or {}
        heat = HeatMetrics(
            value=heat_raw.get("value"),
            label=heat_raw.get("label", ""),
            metric_name=heat_raw.get("metric_name", "hot_value"),
            metrics=heat_raw.get("metrics", {}),
        )
        raw_payload = entry.get("raw_payload") or {}
        title = entry.get("title") or raw_payload.get("Title") or ""
        if not title:
            continue
        hydrated.append(
            HotItem(
                item_id=str(entry.get("item_id") or raw_payload.get("ClusterIdStr") or raw_payload.get("ClusterId") or ""),
                platform=str(entry.get("platform", "toutiao")),
                item_type=str(entry.get("item_type", "topic")),
                title=title,
                url=str(entry.get("url") or raw_payload.get("Url") or ""),
                rank=entry.get("rank"),
                heat=heat,
                summary=str(entry.get("summary") or title),
                category=str(entry.get("category", "")),
                matched_query_ids=tuple(entry.get("matched_query_ids") or ()),
                fetched_at=str(entry.get("fetched_at") or default_fetched_at),
                fetch_status=str(entry.get("fetch_status", "success")),
                raw_payload=raw_payload,
            )
        )
    return hydrated