"""Stable application interfaces for embedding the recommender elsewhere.

The CLI is deliberately only an adapter.  New callers should use
``recommend_user`` (or its async counterpart) and keep their own transport
layer separate from this module.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

from . import recommender, report_writer, user_profile
from .heated_top import HeatedTop


def _next_round(user_dir: Path) -> Path:
    nums = []
    if user_dir.exists():
        for p in user_dir.glob("round_*"):
            try:
                nums.append(int(p.name.removeprefix("round_")))
            except ValueError:
                continue
    return user_dir / f"round_{max(nums, default=0) + 1:03d}"


def recommend_user(
    *,
    user_id: str,
    track_1: str,
    track_2: str = "",
    persona: str = "",
    run_dir: str | Path,
    limit: int = 15,
    **options: Any,
) -> dict[str, Any]:
    """Run one user and persist the standard round directory.

    ``run_dir`` must be a date directory such as ``data/run_20260808``.
    The returned dictionary is suitable for an API response.
    """
    spec = user_profile.UserSpec(
        user_id=user_id, track_1=track_1, track_2=track_2, persona=persona,
    )
    root = Path(run_dir)
    source = str(options.get("source", "v3-hotlist"))
    if source in ("last30days", "both") and not options.get("last30days_config"):
        from .cli import _default_last30days_cli_path

        cli_path = _default_last30days_cli_path()
        if cli_path is None:
            raise FileNotFoundError(
                "last30days is enabled but scripts/last30days.py was not found. "
                "Set LAST30DAYS_CLI_PATH or pass last30days_config explicitly."
            )
        options["last30days_config"] = {
            "cli_path": str(cli_path),
            "days": int(options.pop("last30days_days", 30)),
            "fetch_bodies": bool(options.pop("last30days_fetch_bodies", True)),
            "timeout": float(options.pop("last30days_timeout", 120.0)),
            "save_dir": str(root / "last30days"),
            "platforms": (),
        }
    user_dir = root / user_id
    round_dir = _next_round(user_dir)
    payload = recommender.run_one_user(
        spec,
        data_dir=root / "_runtime",
        limit=limit,
        user_cache_root=root,
        hot_cache_dir=root / "hot_cache",
        **options,
    )
    inp = payload.get("input", {}) or {}
    report_writer.write_user_report(
        round_dir / "outputs", user_id=user_id,
        track_1=inp.get("track_1", track_1), track_2=inp.get("track_2", track_2),
        persona=inp.get("persona", persona),
        recommendations=payload.get("recommendations") or [],
        searched_articles=payload.get("searched_articles") or [],
        summary=payload.get("summary") or "",
    )
    input_dir = round_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "input.json").write_text(
        json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload["run_dir"] = str(root)
    payload["round_dir"] = str(round_dir)
    return payload


class RecommendationService:
    """Concurrency-safe facade for callers handling simultaneous users."""

    def __init__(self, *, max_concurrency: int = 3):
        self._semaphore = asyncio.Semaphore(min(max(1, max_concurrency), 3))
        self._user_locks: dict[str, asyncio.Lock] = {}

    async def recommend_user(self, **kwargs: Any) -> dict[str, Any]:
        user_id = str(kwargs.get("user_id", ""))
        lock = self._user_locks.setdefault(user_id, asyncio.Lock())
        async with self._semaphore, lock:
            return await asyncio.to_thread(recommend_user, **kwargs)


def summarize_daily_hot(*, run_dir: str | Path) -> dict[str, Any]:
    """Read the day's hot-cache files and write a transport-neutral summary.

    This is intentionally a small, deterministic hook.  A later LLM summary
    or push adapter can consume the returned ``items`` without changing the
    recommendation pipeline.
    """
    root = Path(run_dir)
    cache = root / "hot_cache"
    items: list[dict[str, Any]] = []
    for path in sorted(cache.glob("**/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            items.extend(x for x in data if isinstance(x, dict))
    result = {"date": root.name.removeprefix("run_"), "count": len(items), "items": items}
    target = root / "daily_summary"
    target.mkdir(parents=True, exist_ok=True)
    (target / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


__all__ = ["RecommendationService", "HeatedTop"]
