"""Business-day rules for the daily hot-topic workflow."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAILY_CUTOFF_HOUR = 8


def _in_shanghai(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(SHANGHAI)


def is_before_daily_cutoff(now: datetime) -> bool:
    """Return whether *now* falls before 08:00 in Shanghai."""
    return _in_shanghai(now).hour < DAILY_CUTOFF_HOUR


def business_date(now: datetime) -> date:
    """Return the Shanghai business date containing *now*."""
    local_now = _in_shanghai(now)
    if local_now.hour < DAILY_CUTOFF_HOUR:
        return local_now.date() - timedelta(days=1)
    return local_now.date()
