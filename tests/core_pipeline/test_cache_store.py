from datetime import datetime, timedelta, timezone

from src.core_pipeline.cache_store import CacheStore


def test_cache_store_reads_fresh_entry(tmp_path):
    store = CacheStore(tmp_path, ttl_days=7, now=lambda: datetime(2026, 6, 23, tzinfo=timezone.utc))
    store.write("detail:baidu:test", {"value": 1}, fetched_at="2026-06-20T00:00:00+00:00")

    assert store.read("detail:baidu:test") == {"value": 1}


def test_cache_store_ignores_expired_entry(tmp_path):
    store = CacheStore(tmp_path, ttl_days=7, now=lambda: datetime(2026, 6, 23, tzinfo=timezone.utc))
    store.write("detail:baidu:test", {"value": 1}, fetched_at="2026-01-01T00:00:00+00:00")

    assert store.read("detail:baidu:test") is None


def test_cache_store_bypasses_reads_when_refresh_is_true(tmp_path):
    store = CacheStore(tmp_path, ttl_days=7, refresh=True, now=lambda: datetime(2026, 6, 23, tzinfo=timezone.utc))
    store.write("dailyhot:weibo:today:2026-06-23", {"rows": []}, fetched_at="2026-06-23T00:00:00+00:00")

    assert store.read("dailyhot:weibo:today:2026-06-23") is None
