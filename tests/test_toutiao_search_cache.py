import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from heated_topics_v3.contracts import HeatMetrics, HotItem
import heated_topics_v3.toutiao_search_cache as search_cache
from heated_topics_v3.toutiao_search_cache import (
    get_or_fetch_search_items,
    search_cache_path,
)


def _item(article_id: str = "101") -> HotItem:
    return HotItem(
        item_id=f"toutiao_search_{article_id}",
        platform="toutiao",
        item_type="search_result",
        title=f"Article {article_id}",
        url=f"https://www.toutiao.com/group/{article_id}/",
        rank=1,
        heat=HeatMetrics(
            value=10,
            label="10",
            metric_name="search_rank",
            metrics={"search_rank": 10},
        ),
        summary="summary",
        category="search",
        matched_query_ids=("query_1",),
        fetched_at="2026-07-18T10:00:00+08:00",
        fetch_status="success",
        raw_payload={"source_kind": "search_result", "search_phrase": "AI Agent"},
    )


def test_same_day_same_parameters_reuse_cached_items(tmp_path: Path):
    calls = 0

    def fetch_live(_remaining_seconds):
        nonlocal calls
        calls += 1
        return [_item()]

    first, first_source = get_or_fetch_search_items(
        tmp_path,
        "2026-07-18",
        "AI Agent",
        1,
        10,
        "2026-07-18T10:00:00+08:00",
        fetch_live,
    )
    second, second_source = get_or_fetch_search_items(
        tmp_path,
        "2026-07-18",
        " AI   Agent ",
        1,
        10,
        "2026-07-18T11:00:00+08:00",
        fetch_live,
    )

    assert calls == 1
    assert second == first
    assert (first_source, second_source) == ("fresh", "cache")


def test_cache_key_isolates_date_and_pagination_parameters(tmp_path: Path):
    paths = {
        search_cache_path(tmp_path, "2026-07-18", "AI Agent", 1, 10),
        search_cache_path(tmp_path, "2026-07-19", "AI Agent", 1, 10),
        search_cache_path(tmp_path, "2026-07-18", "AI Agent", 2, 10),
        search_cache_path(tmp_path, "2026-07-18", "AI Agent", 1, 20),
    }

    assert len(paths) == 4
    assert search_cache_path(
        tmp_path, "2026-07-18", "AI Agent", 1, 10
    ) == search_cache_path(tmp_path, "2026-07-18", " AI   Agent ", 1, 10)


@pytest.mark.parametrize(
    ("date", "search_pages", "per_page"),
    [
        ("2026-07-19", 1, 10),
        ("2026-07-18", 2, 10),
        ("2026-07-18", 1, 20),
    ],
)
def test_changed_date_or_pagination_fetches_fresh(
    tmp_path: Path, date: str, search_pages: int, per_page: int
):
    calls = 0

    def fetch_live(_remaining_seconds):
        nonlocal calls
        calls += 1
        return [_item(str(100 + calls))]

    get_or_fetch_search_items(
        tmp_path, "2026-07-18", "AI Agent", 1, 10,
        "2026-07-18T10:00:00+08:00", fetch_live,
    )
    _, source = get_or_fetch_search_items(
        tmp_path, date, "AI Agent", search_pages, per_page,
        "2026-07-19T10:00:00+08:00", fetch_live,
    )

    assert calls == 2
    assert source == "fresh"


def test_empty_live_result_is_not_cached(tmp_path: Path):
    items, source = get_or_fetch_search_items(
        tmp_path,
        "2026-07-18",
        "不存在",
        1,
        10,
        "2026-07-18T10:00:00+08:00",
        lambda _remaining: [],
    )

    assert items == []
    assert source == "fresh"
    assert not search_cache_path(
        tmp_path, "2026-07-18", "不存在", 1, 10
    ).exists()


def test_keyword_placeholder_is_not_cached(tmp_path: Path):
    placeholder = _item()
    placeholder.raw_payload["source_kind"] = "search_keyword_hit"

    items, source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", "AI Agent", 1, 10,
        "2026-07-18T10:00:00+08:00", lambda _remaining: [placeholder],
    )

    assert items == [placeholder]
    assert source == "fresh"
    assert not search_cache_path(
        tmp_path, "2026-07-18", "AI Agent", 1, 10
    ).exists()


def test_cache_write_failure_does_not_hide_live_results(tmp_path: Path, monkeypatch):
    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(search_cache, "_save_search_items", fail_write)

    items, source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", "AI Agent", 1, 10,
        "2026-07-18T10:00:00+08:00", lambda _remaining: [_item()],
    )

    assert items == [_item()]
    assert source == "fresh"


def test_malformed_cache_is_replaced_after_successful_fetch(tmp_path: Path):
    path = search_cache_path(tmp_path, "2026-07-18", "AI Agent", 1, 10)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    calls = 0

    def fetch_live(_remaining_seconds):
        nonlocal calls
        calls += 1
        return [_item("202")]

    items, source = get_or_fetch_search_items(
        tmp_path,
        "2026-07-18",
        "AI Agent",
        1,
        10,
        "2026-07-18T12:00:00+08:00",
        fetch_live,
    )

    assert calls == 1
    assert source == "fresh"
    assert items[0].item_id == "toutiao_search_202"
    assert json.loads(path.read_text(encoding="utf-8"))["items"]
    assert list(path.parent.glob(".toutiao_search_*.json")) == []


def test_concurrent_same_key_executes_one_live_fetch(tmp_path: Path):
    calls = 0
    entered = threading.Event()
    release = threading.Event()

    def fetch_live(_remaining_seconds):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=1)
        return [_item()]

    def run():
        return get_or_fetch_search_items(
            tmp_path, "2026-07-18", "AI Agent", 1, 10,
            "2026-07-18T10:00:00+08:00", fetch_live,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        assert entered.wait(timeout=1)
        second = pool.submit(run)
        time.sleep(0.05)
        release.set()
        results = [first.result(timeout=1), second.result(timeout=1)]

    assert calls == 1
    assert {source for _, source in results} == {"fresh", "cache_after_wait"}


def test_held_lock_times_out_without_duplicate_fetch(tmp_path: Path):
    cache_path = search_cache_path(tmp_path, "2026-07-18", "AI Agent", 1, 10)
    cache_path.parent.mkdir(parents=True)
    lock_path = cache_path.with_suffix(".lock")
    # Simulate another process holding the lock by pre-creating the lock file.
    lock_path.touch()
    called = False

    def fetch_live(_remaining_seconds):
        nonlocal called
        called = True
        return [_item()]

    try:
        items, source = get_or_fetch_search_items(
            tmp_path, "2026-07-18", "AI Agent", 1, 10,
            "2026-07-18T10:00:00+08:00", fetch_live,
            lock_wait_seconds=0.05,
        )
    finally:
        lock_path.unlink(missing_ok=True)

    assert items == []
    assert source == "lock_timeout"
    assert called is False


def test_expired_deadline_does_not_fetch_live(tmp_path: Path):
    called = False

    def fetch_live(_remaining_seconds):
        nonlocal called
        called = True
        return [_item()]

    items, source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", "AI Agent", 1, 10,
        "2026-07-18T10:00:00+08:00", fetch_live,
        deadline=9.0,
        monotonic=lambda: 10.0,
    )

    assert items == []
    assert source == "deadline_exceeded"
    assert called is False


def test_failed_leader_releases_lock_for_later_retry(tmp_path: Path):
    def fail(_remaining_seconds):
        raise RuntimeError("upstream failed")

    with pytest.raises(RuntimeError, match="upstream failed"):
        get_or_fetch_search_items(
            tmp_path, "2026-07-18", "AI Agent", 1, 10,
            "2026-07-18T10:00:00+08:00", fail,
        )

    items, source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", "AI Agent", 1, 10,
        "2026-07-18T10:01:00+08:00", lambda _remaining: [_item()],
        lock_wait_seconds=0.05,
    )

    assert items == [_item()]
    assert source == "fresh"
