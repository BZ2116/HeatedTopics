import json
from pathlib import Path

import pytest

from heated_topics_v3.hot_board_cache import (
    DEFAULT_HOT_BOARD_SUBDIR,
    get_or_fetch_hot_board,
    hot_board_cache_path,
    load_hot_board_snapshot,
    save_hot_board_snapshot,
    utc8_day_offset,
    utc8_today,
)
from heated_topics_v3.contracts import HeatMetrics, HotBoardSnapshot, HotItem


def _hot_item(cluster_id: str, title: str, hot_value: int, rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"toutiao_{cluster_id}",
        platform="toutiao",
        item_type="topic",
        title=title,
        url=f"https://www.toutiao.com/group/{cluster_id}/",
        rank=rank,
        heat=HeatMetrics(
            value=hot_value,
            label=str(hot_value),
            metric_name="hot_value",
            metrics={"hot_value": hot_value},
        ),
        summary=title,
        category="",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={
            "ClusterId": cluster_id,
            "Title": title,
            "Url": f"https://www.toutiao.com/group/{cluster_id}/",
            "HotValue": hot_value,
        },
    )


def _hot_board_response_json(items: list[dict]) -> str:
    return json.dumps(
        {"status": "success", "data": items},
        ensure_ascii=False,
    )


def test_utc8_today_format_is_iso_date():
    today = utc8_today()
    assert len(today) == 10
    assert today[4] == "-" and today[7] == "-"


def test_utc8_day_offset_handles_month_boundary():
    assert utc8_day_offset("2026-07-01", days=-1) == "2026-06-30"
    assert utc8_day_offset("2026-01-01", days=-1) == "2025-12-31"
    assert utc8_day_offset("2026-07-13", days=0) == "2026-07-13"
    assert utc8_day_offset("2026-07-13", days=1) == "2026-07-14"


def test_hot_board_cache_path_layout(tmp_path: Path):
    path = hot_board_cache_path(tmp_path, "2026-07-13")
    assert path == tmp_path / DEFAULT_HOT_BOARD_SUBDIR / "2026-07-13.json"


def test_get_or_fetch_writes_cache_for_today(tmp_path: Path):
    date = "2026-07-13"
    response = _hot_board_response_json(
        [
            {"ClusterId": "1", "Title": "Sample A", "Url": "https://www.toutiao.com/group/1/", "HotValue": 1234567},
        ]
    )

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        return response

    snapshot, source = get_or_fetch_hot_board(tmp_path, date, fetcher=fake_fetcher)
    assert source == "fresh"
    assert len(snapshot.items) == 1
    assert snapshot.items[0].title == "Sample A"
    assert snapshot.items[0].heat.value == 1234567
    assert hot_board_cache_path(tmp_path, date).exists()


def test_get_or_fetch_reads_cache_on_second_call(tmp_path: Path):
    date = "2026-07-13"
    first_response = _hot_board_response_json(
        [{"ClusterId": "1", "Title": "Original", "Url": "https://www.toutiao.com/group/1/", "HotValue": 100}]
    )
    get_or_fetch_hot_board(tmp_path, date, fetcher=lambda _u, _t: first_response)

    def boom(_url: str, _t: int) -> str:
        raise AssertionError("should not fetch when cache present")

    snapshot, source = get_or_fetch_hot_board(tmp_path, date, fetcher=boom)
    assert source == "cache"
    assert snapshot.items[0].title == "Original"


def test_get_or_fetch_falls_back_to_yesterday(tmp_path: Path):
    yesterday = "2026-07-12"
    today = "2026-07-13"

    snapshot_y = HotBoardSnapshot(
        date=yesterday,
        fetched_at="2026-07-12T08:00:00+08:00",
        items=(_hot_item("y1", "Yesterday Topic", 999000),),
    )
    save_hot_board_snapshot(tmp_path, snapshot_y)

    def empty_fetcher(_url: str, _t: int) -> str:
        return json.dumps({"status": "success", "data": []})

    snapshot, source = get_or_fetch_hot_board(tmp_path, today, fetcher=empty_fetcher)
    assert source == "fallback_yesterday"
    assert snapshot.date == yesterday
    assert snapshot.items[0].title == "Yesterday Topic"


def test_get_or_fetch_raises_when_both_today_and_yesterday_missing(tmp_path: Path):
    def empty_fetcher(_url: str, _t: int) -> str:
        return json.dumps({"status": "success", "data": []})

    with pytest.raises(RuntimeError) as exc_info:
        get_or_fetch_hot_board(
            tmp_path, "2026-07-13", fetcher=empty_fetcher, allow_yesterday_fallback=True,
        )
    assert "2026-07-13" in str(exc_info.value)


def test_get_or_fetch_force_refresh_bypasses_cache(tmp_path: Path):
    date = "2026-07-13"
    original = _hot_board_response_json(
        [{"ClusterId": "1", "Title": "Original", "Url": "https://www.toutiao.com/group/1/", "HotValue": 100}]
    )
    get_or_fetch_hot_board(tmp_path, date, fetcher=lambda _u, _t: original)

    def replacement_fetcher(_url: str, _t: int) -> str:
        return _hot_board_response_json(
            [{"ClusterId": "2", "Title": "Fresh", "Url": "https://www.toutiao.com/group/2/", "HotValue": 200}]
        )

    snapshot, source = get_or_fetch_hot_board(
        tmp_path, date, fetcher=replacement_fetcher, force_refresh=True,
    )
    assert source == "fresh"
    assert snapshot.items[0].title == "Fresh"


def test_save_and_load_snapshot_round_trip(tmp_path: Path):
    snapshot = HotBoardSnapshot(
        date="2026-07-13",
        fetched_at="2026-07-13T08:00:00+08:00",
        items=(
            _hot_item("1", "Topic A", 5000000, rank=1),
            _hot_item("2", "Topic B", 1500000, rank=2),
        ),
    )
    save_hot_board_snapshot(tmp_path, snapshot)

    loaded = load_hot_board_snapshot(tmp_path, "2026-07-13")
    assert loaded is not None
    assert loaded.date == "2026-07-13"
    assert len(loaded.items) == 2
    assert loaded.items[0].title == "Topic A"
    assert loaded.items[0].heat.value == 5000000
    assert loaded.items[0].rank == 1
    assert loaded.items[1].title == "Topic B"


def test_load_returns_none_when_file_missing(tmp_path: Path):
    assert load_hot_board_snapshot(tmp_path, "2026-07-13") is None


def test_load_returns_none_when_date_mismatches(tmp_path: Path):
    snapshot = HotBoardSnapshot(
        date="2026-07-12",
        fetched_at="2026-07-12T08:00:00+08:00",
        items=(_hot_item("1", "Yesterday", 100),),
    )
    save_hot_board_snapshot(tmp_path, snapshot)
    assert load_hot_board_snapshot(tmp_path, "2026-07-13") is None


def test_save_uses_atomic_write(tmp_path: Path):
    snapshot = HotBoardSnapshot(
        date="2026-07-13",
        fetched_at="2026-07-13T08:00:00+08:00",
        items=(_hot_item("1", "Atomic", 100),),
    )
    save_hot_board_snapshot(tmp_path, snapshot)
    files = list((tmp_path / DEFAULT_HOT_BOARD_SUBDIR).iterdir())
    assert len(files) == 1
    assert files[0].name == "2026-07-13.json"