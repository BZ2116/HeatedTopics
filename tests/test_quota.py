from pathlib import Path

import pytest

from heated_topics_v3.quota import (
    QuotaExceededError,
    QuotaState,
    check_quota,
    commit_quota,
    load_quota,
)


def test_load_quota_missing_file_returns_zero(tmp_path: Path):
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=0)


def test_load_quota_stale_date_resets(tmp_path: Path):
    (tmp_path / "quota").mkdir()
    (tmp_path / "quota" / "u1.json").write_text(
        '{"date": "2026-07-16", "count": 3}', encoding="utf-8"
    )
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=0)


def test_load_quota_same_day_reads_count(tmp_path: Path):
    (tmp_path / "quota").mkdir()
    (tmp_path / "quota" / "u1.json").write_text(
        '{"date": "2026-07-17", "count": 2}', encoding="utf-8"
    )
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=2)


def test_check_quota_under_limit_passes():
    check_quota(QuotaState(date="2026-07-17", count=2), max_per_day=3)


def test_check_quota_at_limit_raises():
    with pytest.raises(QuotaExceededError, match="今日额度已用完"):
        check_quota(QuotaState(date="2026-07-17", count=3), max_per_day=3)


def test_commit_quota_increments_and_persists(tmp_path: Path):
    commit_quota(tmp_path, "u1", "2026-07-17")
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=1)
    new = commit_quota(tmp_path, "u1", "2026-07-17")
    assert new == QuotaState(date="2026-07-17", count=2)


def test_commit_quota_stale_date_starts_from_zero(tmp_path: Path):
    (tmp_path / "quota").mkdir()
    (tmp_path / "quota" / "u1.json").write_text(
        '{"date": "2026-07-16", "count": 3}', encoding="utf-8"
    )
    new = commit_quota(tmp_path, "u1", "2026-07-17")
    assert new == QuotaState(date="2026-07-17", count=1)
