import json
import threading
import time
from dataclasses import replace
from datetime import datetime

from heated_topics_v3.collection import collect_v1_daily
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.storage import FileRepository


NOW = datetime.fromisoformat("2026-07-13T08:01:00+08:00")
COLLECTED_AT = NOW.isoformat()


def _item(platform: str, sequence: int) -> HotItem:
    return HotItem(
        item_id=f"{platform}_{sequence}",
        platform=platform,
        title=f"{platform} topic {sequence}",
        url=f"https://example.test/{platform}/{sequence}",
        rank=sequence,
        heat=HeatMetrics(sequence, str(sequence), "rank"),
        summary=f"{platform} summary {sequence}",
        publication_time=None,
        collected_at=COLLECTED_AT,
        raw_payload={"sequence": sequence},
    )


class FakeProvider:
    def __init__(self, platform: str, count: int = 2, *, board_error: Exception | None = None):
        self.platform = platform
        self.items = tuple(_item(platform, sequence) for sequence in range(1, count + 1))
        self.board_error = board_error
        self.detail_calls: list[str] = []
        self.active_details = 0
        self.maximum_active_details = 0
        self._lock = threading.Lock()

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        if self.board_error is not None:
            raise self.board_error
        items = tuple(replace(item, collected_at=collected_at) for item in self.items)
        return ProviderCapture(
            json.dumps({"platform": self.platform, "items": len(items)}),
            ".json",
            items,
        )

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        with self._lock:
            self.detail_calls.append(item.item_id)
            self.active_details += 1
            self.maximum_active_details = max(self.maximum_active_details, self.active_details)
        time.sleep(0.01)
        with self._lock:
            self.active_details -= 1
        return ItemDetail(
            item_id=item.item_id,
            content=f"detail for {item.item_id}",
            content_status="full_text",
            publication_time=item.publication_time,
            collected_at=collected_at,
            source_url=item.url,
            fetch_status="success",
        )


class DegradedDetailProvider(FakeProvider):
    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        self.detail_calls.append(item.item_id)
        return ItemDetail(
            item_id=item.item_id,
            content=item.summary,
            content_status="summary",
            publication_time=item.publication_time,
            collected_at=collected_at,
            source_url=item.url,
            fetch_status="partial",
        )


class SummaryDetailProvider(DegradedDetailProvider):
    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        detail = super().fetch_detail(item, collected_at)
        return replace(detail, fetch_status="success")


def test_collects_both_platforms_and_persists_raw_normalized_and_ordered_details(tmp_path):
    repository = FileRepository(tmp_path)
    providers = {"toutiao": FakeProvider("toutiao"), "juejin": FakeProvider("juejin")}

    snapshot = collect_v1_daily(NOW, repository, providers)

    day = tmp_path / "daily_hot_lists" / "2026-07-13"
    assert tuple(snapshot.items_by_platform) == ("toutiao", "juejin")
    assert [item.item_id for item in snapshot.items_by_platform["toutiao"]] == [
        "toutiao_1",
        "toutiao_2",
    ]
    assert json.loads((day / "raw" / "toutiao.json").read_text("utf-8"))["platform"] == "toutiao"
    assert json.loads((day / "raw" / "juejin.json").read_text("utf-8"))["platform"] == "juejin"
    assert [row["item_id"] for row in json.loads((day / "normalized" / "toutiao.json").read_text("utf-8"))] == [
        "toutiao_1",
        "toutiao_2",
    ]
    assert [row["item_id"] for row in json.loads((day / "normalized" / "juejin.json").read_text("utf-8"))] == [
        "juejin_1",
        "juejin_2",
    ]
    assert (day / "details" / "toutiao_1.txt").read_text("utf-8") == "detail for toutiao_1"
    assert (day / "details" / "toutiao_2.txt").read_text("utf-8") == "detail for toutiao_2"
    assert (day / "details" / "juejin_1.txt").read_text("utf-8") == "detail for juejin_1"
    assert (day / "details" / "juejin_2.txt").read_text("utf-8") == "detail for juejin_2"


def test_detail_collection_caps_each_platform_pool_at_three_workers(tmp_path):
    providers = {"toutiao": FakeProvider("toutiao", 6), "juejin": FakeProvider("juejin", 6)}

    collect_v1_daily(NOW, FileRepository(tmp_path), providers)

    assert 1 < providers["toutiao"].maximum_active_details <= 3
    assert 1 < providers["juejin"].maximum_active_details <= 3


def test_repeated_collection_reuses_saved_details(tmp_path):
    repository = FileRepository(tmp_path)
    first = {"toutiao": FakeProvider("toutiao"), "juejin": FakeProvider("juejin")}
    collect_v1_daily(NOW, repository, first)
    second = {"toutiao": FakeProvider("toutiao"), "juejin": FakeProvider("juejin")}

    collect_v1_daily(NOW, repository, second)

    assert second["toutiao"].detail_calls == []
    assert second["juejin"].detail_calls == []


def test_reordered_board_reuses_details_by_item_id_without_misassigning_sequences(tmp_path):
    repository = FileRepository(tmp_path)
    first = {"toutiao": FakeProvider("toutiao"), "juejin": FakeProvider("juejin")}
    collect_v1_daily(NOW, repository, first)
    second = {"toutiao": FakeProvider("toutiao"), "juejin": FakeProvider("juejin")}
    second["toutiao"].items = tuple(reversed(second["toutiao"].items))
    second["juejin"].items = tuple(reversed(second["juejin"].items))

    collect_v1_daily(NOW, repository, second)

    details = tmp_path / "daily_hot_lists" / "2026-07-13" / "details"
    assert second["toutiao"].detail_calls == []
    assert second["juejin"].detail_calls == []
    assert (details / "toutiao_1.txt").read_text("utf-8") == "detail for toutiao_2"
    assert (details / "toutiao_2.txt").read_text("utf-8") == "detail for toutiao_1"
    assert (details / "juejin_1.txt").read_text("utf-8") == "detail for juejin_2"
    assert (details / "juejin_2.txt").read_text("utf-8") == "detail for juejin_1"


def test_degraded_item_detail_marks_platform_partial_and_stays_partial_when_cached(tmp_path):
    repository = FileRepository(tmp_path)
    first = {
        "toutiao": DegradedDetailProvider("toutiao", 1),
        "juejin": FakeProvider("juejin", 1),
    }

    initial = collect_v1_daily(NOW, repository, first)
    second = {
        "toutiao": DegradedDetailProvider("toutiao", 1),
        "juejin": FakeProvider("juejin", 1),
    }
    repeated = collect_v1_daily(NOW, repository, second)

    assert initial.platform_statuses[0].status == "partial"
    assert repeated.platform_statuses[0].status == "partial"
    assert second["toutiao"].detail_calls == []
    statuses = json.loads(
        (tmp_path / "daily_hot_lists" / "2026-07-13" / "collection_status.json").read_text("utf-8")
    )
    assert statuses[0]["status"] == "partial"
    assert statuses[0]["error"] == "detail_fetch_failed:toutiao_1"


def test_non_full_content_status_marks_platform_partial_even_when_fetch_succeeds(tmp_path):
    repository = FileRepository(tmp_path)
    providers = {
        "toutiao": SummaryDetailProvider("toutiao", 1),
        "juejin": FakeProvider("juejin", 1),
    }

    snapshot = collect_v1_daily(NOW, repository, providers)

    assert snapshot.platform_statuses[0].status == "partial"
    assert snapshot.platform_statuses[0].error == "detail_fetch_failed:toutiao_1"


def test_platform_failure_is_isolated_and_written_to_collection_status(tmp_path):
    repository = FileRepository(tmp_path)
    providers = {
        "toutiao": FakeProvider("toutiao", board_error=RuntimeError("request failed: token=private")),
        "juejin": FakeProvider("juejin"),
    }

    snapshot = collect_v1_daily(NOW, repository, providers)

    day = tmp_path / "daily_hot_lists" / "2026-07-13"
    statuses = json.loads((day / "collection_status.json").read_text("utf-8"))
    assert tuple(snapshot.items_by_platform) == ("juejin",)
    assert [(status["platform"], status["status"], status["item_count"]) for status in statuses] == [
        ("toutiao", "failed", 0),
        ("juejin", "success", 2),
    ]
    assert statuses[0]["error"] == "RuntimeError"
    assert not (day / "raw" / "toutiao.json").exists()
    assert not (day / "normalized" / "toutiao.json").exists()
    assert (day / "normalized" / "juejin.json").is_file()
    assert (day / "details" / "juejin_1.txt").is_file()
    assert "private" not in (day / "collection_status.json").read_text("utf-8")


def test_empty_board_capture_is_failed_not_success(tmp_path):
    repository = FileRepository(tmp_path)
    providers = {
        "toutiao": FakeProvider("toutiao", count=0),
        "juejin": FakeProvider("juejin", count=1),
    }

    snapshot = collect_v1_daily(NOW, repository, providers)

    assert "toutiao" not in snapshot.items_by_platform
    assert snapshot.platform_statuses[0].status == "failed"
    assert snapshot.platform_statuses[0].item_count == 0
    assert snapshot.platform_statuses[1].status == "success"
    assert not (
        repository.daily_dir("2026-07-13") / "normalized" / "toutiao.json"
    ).exists()
