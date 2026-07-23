"""Daily single-flight caches for Bilibili search / article fetches.

Mirrors the design of `baidu_cache.py` (which itself mirrors `toutiao_search_cache.py`):

- File-based advisory lock (`<cache>.lock`) for cross-process coordination.
- atomic write via temp + `Path.replace`.
- `schema_version` in each payload for forward-compatible upgrades.
- Returns `(<value>, source)` where source ∈ {"cache", "cache_after_wait",
  "fresh", "deadline_exceeded", "lock_timeout"}.

Identity fields (`date`, `word`, `article_id`) are written into each payload
and verified on read, so a stale or mismatched file is rejected.

Each public function has a `_with_record` sibling that exposes the source
string — the pipeline uses the simple form, tests use the recorded form.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

SEARCH_SUBDIR = "bilibili/search"
ARTICLE_SUBDIR = "bilibili/articles"


# ---- low-level helpers ----

def _acquire_lock_nonblocking(lock_path: Path) -> int | None:
    try:
        return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def _release_lock(lock_path: Path, fd: int) -> None:
    try:
        os.close(fd)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _normalize_word(word: str) -> str:
    return " ".join(str(word).split())


def _word_digest(word: str) -> str:
    return hashlib.sha256(_normalize_word(word).encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".bilibili_cache_", suffix=".json", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _load_payload(path: Path) -> dict | None:
    """Read a JSON cache file and return the payload as a dict, or None on any failure.

    Catches missing file, decode errors, and OS errors uniformly so callers can
    focus on cache-specific identity / schema checks.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _single_flight(
    *,
    cache_path: Path,
    deadline: float | None,
    lock_wait_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    load_cached: Callable[[], Any | None],
    save_cached: Callable[[Any], None],
    live_fetch: Callable[[float], Any],
    empty_marker: Any,
    skip_cached: bool = False,
) -> tuple[Any, str]:
    cached = None if skip_cached else load_cached()
    if cached is not None:
        return cached, "cache"

    now = monotonic()
    if deadline is not None and now >= deadline:
        return empty_marker, "deadline_exceeded"

    lock_path = cache_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    wait_deadline = now + max(0.0, lock_wait_seconds)
    if deadline is not None:
        wait_deadline = min(wait_deadline, deadline)

    lock_fd: int | None = None
    while True:
        lock_fd = _acquire_lock_nonblocking(lock_path)
        if lock_fd is not None:
            break
        now = monotonic()
        if now >= wait_deadline:
            return empty_marker, "lock_timeout"
        sleep(min(0.02, wait_deadline - now))

    try:
        cached = None if skip_cached else load_cached()
        if cached is not None:
            return cached, "cache_after_wait"

        now = monotonic()
        if deadline is not None and now >= deadline:
            return empty_marker, "deadline_exceeded"
        remaining = float("inf") if deadline is None else deadline - now
        result = live_fetch(remaining)
        try:
            save_cached(result)
        except (OSError, TypeError, ValueError):
            pass
        return result, "fresh"
    finally:
        if lock_fd is not None:
            _release_lock(lock_path, lock_fd)


# ---- search (per-word key) ----

def _search_path(cache_root: Path | str, date: str, word: str) -> Path:
    return Path(cache_root) / SEARCH_SUBDIR / date / f"{_word_digest(word)}.json"


def get_or_fetch_search_with_record(
    cache_root: Path | str,
    date: str,
    word: str,
    fetch_live: Callable[[str], list],
    *,
    deadline: float | None = None,
    lock_wait_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    force_refresh: bool = False,
) -> tuple[list, str]:
    path = _search_path(cache_root, date, word)
    normalized_word = _normalize_word(word)

    def load_cached() -> list | None:
        payload = _load_payload(path)
        if payload is None:
            return None
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if payload.get("date") != date:
            return None
        if payload.get("word") != normalized_word:
            return None
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids:
            return None
        return ids

    def save_cached(value: list) -> None:
        if not isinstance(value, list) or not value:
            return
        payload = {
            "schema_version": SCHEMA_VERSION,
            "date": date,
            "word": normalized_word,
            "ids": value,
        }
        _atomic_write_json(path, payload)

    return _single_flight(
        cache_path=path,
        deadline=deadline,
        lock_wait_seconds=lock_wait_seconds,
        monotonic=monotonic,
        sleep=sleep,
        load_cached=load_cached,
        save_cached=save_cached,
        live_fetch=lambda remaining: fetch_live(word),
        empty_marker=[],
        skip_cached=force_refresh,
    )


def get_or_fetch_search(
    cache_root: Path | str,
    date: str,
    word: str,
    fetch_live: Callable[[str], list],
    **kwargs: Any,
) -> tuple[list, str]:
    return get_or_fetch_search_with_record(cache_root, date, word, fetch_live, **kwargs)


# ---- article (per-id key) ----

def _article_path(cache_root: Path | str, date: str, article_id: str) -> Path:
    return Path(cache_root) / ARTICLE_SUBDIR / date / f"{article_id}.json"


def get_or_fetch_article_with_record(
    cache_root: Path | str,
    date: str,
    article_id: str,
    fetch_live: Callable[[str], dict],
    *,
    deadline: float | None = None,
    lock_wait_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    force_refresh: bool = False,
) -> tuple[dict, str]:
    path = _article_path(cache_root, date, article_id)

    def load_cached() -> dict | None:
        payload = _load_payload(path)
        if payload is None:
            return None
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if payload.get("date") != date:
            return None
        if payload.get("article_id") != article_id:
            return None
        value = {
            k: v for k, v in payload.items() if k not in {"schema_version", "date", "article_id"}
        }
        if not value:
            return None
        return value

    def save_cached(value: dict) -> None:
        if not isinstance(value, dict) or not value:
            return
        payload = {
            "schema_version": SCHEMA_VERSION,
            "date": date,
            "article_id": article_id,
            **value,
        }
        _atomic_write_json(path, payload)

    return _single_flight(
        cache_path=path,
        deadline=deadline,
        lock_wait_seconds=lock_wait_seconds,
        monotonic=monotonic,
        sleep=sleep,
        load_cached=load_cached,
        save_cached=save_cached,
        live_fetch=lambda remaining: fetch_live(article_id),
        empty_marker={},
        skip_cached=force_refresh,
    )


def get_or_fetch_article(
    cache_root: Path | str,
    date: str,
    article_id: str,
    fetch_live: Callable[[str], dict],
    **kwargs: Any,
) -> tuple[dict, str]:
    return get_or_fetch_article_with_record(cache_root, date, article_id, fetch_live, **kwargs)