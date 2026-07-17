"""Per-user daily quota state.

A quota file `state/quota/{user_id}.json` holds `{"date", "count"}`. A day
rolls over automatically: reading with a different `today` resets count to 0.

check/commit are split on purpose: the pipeline calls `check_quota` BEFORE
running (so the 4th request is rejected without spending a search) and
`commit_quota` AFTER a search flow completes (so failed/short-circuited runs
don't consume the quota).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class QuotaExceededError(Exception):
    """Raised by check_quota when the daily limit is already reached."""


@dataclass(frozen=True)
class QuotaState:
    date: str
    count: int


def _quota_path(state_root: Path, user_id: str) -> Path:
    return Path(state_root) / "quota" / f"{user_id}.json"


def load_quota(state_root: Path, user_id: str, today: str) -> QuotaState:
    """Read quota for today; missing file or stale date both mean count=0."""
    path = _quota_path(state_root, user_id)
    if not path.exists():
        return QuotaState(date=today, count=0)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return QuotaState(date=today, count=0)
    if not isinstance(payload, dict) or payload.get("date") != today:
        return QuotaState(date=today, count=0)
    count = payload.get("count", 0)
    if not isinstance(count, int) or count < 0:
        count = 0
    return QuotaState(date=today, count=count)


def check_quota(state: QuotaState, max_per_day: int) -> None:
    """Raise QuotaExceededError when count has reached the limit. No write."""
    if state.count >= max_per_day:
        raise QuotaExceededError("今日额度已用完")


def commit_quota(state_root: Path, user_id: str, today: str) -> QuotaState:
    """Increment today's count by 1 and persist. Write failures are swallowed
    (best-effort) so a full-disk/permission error never discards a produced run."""
    current = load_quota(state_root, user_id, today)
    new_state = QuotaState(date=today, count=current.count + 1)
    path = _quota_path(state_root, user_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"date": new_state.date, "count": new_state.count}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return new_state
