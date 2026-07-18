"""Shared UTC+8 daily cache for parsed Toutiao keyword search results."""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import fcntl

from heated_topics_v3.contracts import HeatMetrics, HotItem


SCHEMA_VERSION = 1
DEFAULT_SEARCH_CACHE_SUBDIR = "toutiao_search"


def search_cache_path(
    cache_root: str | Path,
    date: str,
    keyword: str,
    search_pages: int,
    per_page: int,
) -> Path:
    identity = _cache_identity(keyword, search_pages, per_page)
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Path(cache_root) / DEFAULT_SEARCH_CACHE_SUBDIR / date / f"{digest}.json"


def get_or_fetch_search_items(
    cache_root: str | Path,
    date: str,
    keyword: str,
    search_pages: int,
    per_page: int,
    fetched_at: str,
    fetch_live: Callable[[float], list[HotItem]],
    *,
    deadline: float | None = None,
    lock_wait_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[HotItem], str]:
    cached = _load_search_items(cache_root, date, keyword, search_pages, per_page)
    if cached:
        return cached, "cache"

    now = monotonic()
    if deadline is not None and now >= deadline:
        return [], "deadline_exceeded"

    cache_path = search_cache_path(cache_root, date, keyword, search_pages, per_page)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_suffix(".lock")
    wait_deadline = now + max(0.0, lock_wait_seconds)
    if deadline is not None:
        wait_deadline = min(wait_deadline, deadline)

    with lock_path.open("a+") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                now = monotonic()
                if now >= wait_deadline:
                    source = "deadline_exceeded" if deadline is not None and now >= deadline else "lock_timeout"
                    return [], source
                sleep(min(0.02, wait_deadline - now))

        try:
            cached = _load_search_items(cache_root, date, keyword, search_pages, per_page)
            if cached:
                return cached, "cache_after_wait"

            now = monotonic()
            if deadline is not None and now >= deadline:
                return [], "deadline_exceeded"
            remaining_seconds = float("inf") if deadline is None else deadline - now
            items = fetch_live(remaining_seconds)
            if items and all(_is_cacheable_item(item) for item in items):
                try:
                    _save_search_items(
                        cache_root,
                        date,
                        keyword,
                        search_pages,
                        per_page,
                        fetched_at,
                        items,
                    )
                except (OSError, TypeError, ValueError):
                    pass
            return items, "fresh"
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _cache_identity(keyword: str, search_pages: int, per_page: int) -> dict[str, Any]:
    return {
        "keyword": _normalize_keyword(keyword),
        "search_pages": int(search_pages),
        "per_page": int(per_page),
        "schema_version": SCHEMA_VERSION,
    }


def _normalize_keyword(keyword: str) -> str:
    return " ".join(str(keyword).split())


def _load_search_items(
    cache_root: str | Path,
    date: str,
    keyword: str,
    search_pages: int,
    per_page: int,
) -> list[HotItem] | None:
    path = search_cache_path(cache_root, date, keyword, search_pages, per_page)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = _cache_identity(keyword, search_pages, per_page)
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if payload.get("date") != date:
            return None
        if payload.get("keyword") != identity["keyword"]:
            return None
        if payload.get("search_pages") != identity["search_pages"]:
            return None
        if payload.get("per_page") != identity["per_page"]:
            return None
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            return None
        items = [_hydrate_item(entry) for entry in raw_items]
        if not all(_is_cacheable_item(item) for item in items):
            return None
        return items
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        return None


def _save_search_items(
    cache_root: str | Path,
    date: str,
    keyword: str,
    search_pages: int,
    per_page: int,
    fetched_at: str,
    items: list[HotItem],
) -> Path:
    path = search_cache_path(cache_root, date, keyword, search_pages, per_page)
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = _cache_identity(keyword, search_pages, per_page)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "date": date,
        **identity,
        "fetched_at": fetched_at,
        "items": [asdict(item) for item in items],
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=".toutiao_search_",
        suffix=".json",
        dir=str(path.parent),
    )
    try:
        with open(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def _hydrate_item(entry: Any) -> HotItem:
    if not isinstance(entry, dict):
        raise TypeError("cached search item must be an object")
    heat_raw = entry["heat"]
    if not isinstance(heat_raw, dict):
        raise TypeError("cached heat metrics must be an object")
    return HotItem(
        item_id=str(entry["item_id"]),
        platform=str(entry["platform"]),
        item_type=str(entry["item_type"]),
        title=str(entry["title"]),
        url=str(entry["url"]),
        rank=None if entry.get("rank") is None else int(entry["rank"]),
        heat=HeatMetrics(
            value=None if heat_raw.get("value") is None else int(heat_raw["value"]),
            label=str(heat_raw.get("label", "")),
            metric_name=str(heat_raw["metric_name"]),
            metrics=dict(heat_raw.get("metrics") or {}),
        ),
        summary=str(entry.get("summary", "")),
        category=str(entry.get("category", "")),
        matched_query_ids=tuple(entry.get("matched_query_ids") or ()),
        fetched_at=str(entry["fetched_at"]),
        fetch_status=str(entry["fetch_status"]),
        raw_payload=dict(entry.get("raw_payload") or {}),
    )


def _is_cacheable_item(item: HotItem) -> bool:
    source_kind = str(item.raw_payload.get("source_kind") or "")
    return bool(
        item.item_id
        and item.title
        and item.url
        and item.item_type == "search_result"
        and source_kind != "search_keyword_hit"
    )
