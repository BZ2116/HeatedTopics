"""Generalized daily news collection across sina/thepaper/netease platforms."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping

from heated_topics_v3.collection import collect_news_daily
from heated_topics_v3.contracts import (
    ContentValidation,
    HeatMetrics,
    HotItem,
    ItemDetail,
)
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.storage import FileRepository


NOW = datetime.fromisoformat("2026-07-23T08:01:00+08:00")
BUSINESS_DATE = "2026-07-23"
COLLECTED_AT = NOW.isoformat()


_LONG_BODY = (
    "正文第一段，介绍事件背景，描述发生时间地点和主要人物，并交代事件起因。\n\n"
    "正文第二段，引用公开信息补充细节，说明各方回应、数据来源与相关证据。\n\n"
    "正文第三段，交待后续安排、影响范围、可能的后续进展与尚需确认的信息。\n\n"
    "正文第四段，提供独立第三方观察和专家评论，对事件的长期影响做简要判断。\n"
)


def _item(
    *,
    platform: str,
    item_id: str,
    rank: int | None,
    metrics: Mapping[str, float] | None = None,
) -> HotItem:
    payload_metrics: dict[str, float] = dict(metrics or {})
    primary = next(iter(payload_metrics.values()), None)
    return HotItem(
        item_id=item_id,
        platform=platform,
        title=f"{platform} title {item_id}",
        url=f"https://example.test/{platform}/{item_id}",
        rank=rank,
        heat=HeatMetrics(
            value=primary,
            label="" if primary is None else str(primary),
            metric_name=next(iter(payload_metrics.keys()), "metric"),
            metrics=payload_metrics,
        ),
        summary=f"{platform} summary {item_id}",
        publication_time=None,
        collected_at=COLLECTED_AT,
        raw_payload={"platform": platform, "item_id": item_id},
    )


class FakeNewsProvider:
    def __init__(
        self,
        platform: str,
        items: tuple[HotItem, ...] = (),
        *,
        detail_payloads: Mapping[str, ItemDetail] | None = None,
        hot_error: Exception | None = None,
    ) -> None:
        self.platform = platform
        self.weights: dict[str, float] = {"top_num": 0.7, "comments": 0.3}
        self.absolute_floors: dict[str, float] = {"comments": 1.0}
        self._items = items
        self._detail_payloads = detail_payloads or {}
        self._hot_error = hot_error
        self.hot_calls = 0
        self.search_calls: list[tuple[str, int, int, str]] = []
        self.enrich_calls = 0
        self.detail_calls: list[str] = []
        self._detail_lock = threading.Lock()
        self._active_details = 0
        self.max_active_details = 0

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        self.hot_calls += 1
        if self._hot_error is not None:
            raise self._hot_error
        items = tuple(
            replace(item, collected_at=collected_at) for item in self._items
        )
        return ProviderCapture(
            json.dumps({"platform": self.platform, "count": len(items)}),
            ".json",
            items,
        )

    def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        self.search_calls.append((keyword, page, page_size, collected_at))
        return ProviderCapture(
            json.dumps({"platform": self.platform, "keyword": keyword, "page": page}),
            ".json",
            (),
        )

    def enrich_metrics(
        self, items: tuple[HotItem, ...], collected_at: str
    ) -> tuple[HotItem, ...]:
        self.enrich_calls += 1
        return items

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        with self._detail_lock:
            self.detail_calls.append(item.item_id)
            self._active_details += 1
            self.max_active_details = max(
                self.max_active_details, self._active_details
            )
        try:
            import time as _time
            _time.sleep(0.02)
            payload = self._detail_payloads.get(item.item_id)
            if payload is None:
                payload = ItemDetail(
                    item_id=item.item_id,
                    content=_LONG_BODY,
                    content_status="full_text",
                    publication_time=item.publication_time,
                    collected_at=collected_at,
                    source_url=item.url,
                    fetch_status="success",
                )
            return payload
        finally:
            with self._detail_lock:
                self._active_details -= 1


def _sina_provider() -> FakeNewsProvider:
    full = _item(
        platform="sina_news",
        item_id="sina_news_full",
        rank=1,
        metrics={"top_num": 100.0, "comments": 12.0},
    )
    short = _item(
        platform="sina_news",
        item_id="sina_news_short",
        rank=2,
        metrics={"top_num": 50.0, "comments": 0.0},
    )
    no_metric = _item(
        platform="sina_news",
        item_id="sina_news_no_metric",
        rank=3,
        metrics={},
    )
    return FakeNewsProvider(
        platform="sina_news",
        items=(full, short, no_metric),
        detail_payloads={
            "sina_news_full": ItemDetail(
                item_id="sina_news_full",
                content=_LONG_BODY,
                content_status="full_text",
                publication_time=None,
                collected_at=COLLECTED_AT,
                source_url="https://example.test/sina_news/sina_news_full",
                fetch_status="success",
            ),
            "sina_news_short": ItemDetail(
                item_id="sina_news_short",
                content="一句话不够长。",
                content_status="full_text",
                publication_time=None,
                collected_at=COLLECTED_AT,
                source_url="https://example.test/sina_news/sina_news_short",
                fetch_status="success",
            ),
            "sina_news_no_metric": ItemDetail(
                item_id="sina_news_no_metric",
                content="",
                content_status="title_only",
                publication_time=None,
                collected_at=COLLECTED_AT,
                source_url="https://example.test/sina_news/sina_news_no_metric",
                fetch_status="partial:no_metric",
            ),
        },
    )


def _thepaper_provider() -> FakeNewsProvider:
    one = _item(
        platform="thepaper",
        item_id="thepaper_1",
        rank=1,
        metrics={"interaction_num": 100.0, "praise_times": 12.0},
    )
    return FakeNewsProvider(
        platform="thepaper",
        items=(one,),
    )


def _netease_provider() -> FakeNewsProvider:
    one = _item(
        platform="netease_news",
        item_id="netease_news_1",
        rank=1,
        metrics={"hot_value": 100.0, "comments": 1.0},
    )
    return FakeNewsProvider(
        platform="netease_news",
        items=(one,),
    )


def _build_providers() -> dict[str, FakeNewsProvider]:
    return {
        "sina_news": _sina_provider(),
        "thepaper": _thepaper_provider(),
        "netease_news": _netease_provider(),
    }


def _build_providers_with_failure() -> dict[str, FakeNewsProvider]:
    providers = _build_providers()
    providers["thepaper"]._hot_error = RuntimeError("upstream timeout")
    return providers


def test_daily_collection_publishes_only_full_text_with_heat(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers()

    snapshot = collect_news_daily(NOW, repository, providers)

    day = repository.daily_dir(BUSINESS_DATE)
    sina_status = next(
        status for status in snapshot.platform_statuses
        if status.platform == "sina_news"
    )
    assert sina_status.status == "partial"

    eligible = repository.load_eligible(BUSINESS_DATE, "sina_news")
    assert [item.hot_item.item_id for item in eligible] == ["sina_news_full"]
    assert eligible[0].heat_evidence.source_kind == "official_hot_board"
    assert eligible[0].heat_evidence.qualified_by == ("official_hot_board",)
    assert eligible[0].detail.content_status == "full_text"

    rejected = json.loads((day / "rejected" / "sina_news.json").read_text("utf-8"))
    assert {row["item_id"] for row in rejected} == {
        "sina_news_short",
        "sina_news_no_metric",
    }
    rejected_by_id = {row["item_id"]: row for row in rejected}
    assert "source_url" in rejected_by_id["sina_news_short"]
    assert rejected_by_id["sina_news_short"]["source_url"].startswith(
        "https://example.test/sina_news/"
    )
    assert rejected_by_id["sina_news_no_metric"]["reasons"] == ["partial:no_metric"]
    assert isinstance(rejected_by_id["sina_news_short"]["reasons"], list)
    assert rejected_by_id["sina_news_short"]["reasons"]


def test_collection_fetches_each_board_once_and_isolates_platform_failure(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers_with_failure()

    snapshot = collect_news_daily(NOW, repository, providers)

    assert providers["sina_news"].hot_calls == 1
    assert providers["thepaper"].hot_calls == 1
    assert providers["netease_news"].hot_calls == 1

    statuses = {status.platform: status for status in snapshot.platform_statuses}
    assert statuses["sina_news"].status == "partial"
    assert statuses["sina_news"].item_count == 3
    assert statuses["thepaper"].status == "failed"
    assert statuses["thepaper"].item_count == 0
    assert statuses["netease_news"].status == "success"
    assert statuses["netease_news"].item_count == 1

    day = repository.daily_dir(BUSINESS_DATE)
    assert (day / "raw" / "sina_news.json").is_file()
    assert (day / "normalized" / "sina_news.json").is_file()
    assert (day / "eligible" / "sina_news.json").is_file()
    assert (day / "rejected" / "sina_news.json").is_file()
    assert not (day / "raw" / "thepaper.json").exists()
    assert not (day / "normalized" / "thepaper.json").exists()
    assert not (day / "eligible" / "thepaper.json").exists()
    assert not (day / "rejected" / "thepaper.json").exists()
    assert (day / "normalized" / "netease_news.json").is_file()
    assert (day / "eligible" / "netease_news.json").is_file()

    statuses_payload = json.loads(
        (day / "collection_status.json").read_text("utf-8")
    )
    assert {(row["platform"], row["status"]) for row in statuses_payload} == {
        ("sina_news", "partial"),
        ("thepaper", "failed"),
        ("netease_news", "success"),
    }


def test_detail_files_use_stable_item_id_and_no_summary_fallback(tmp_path):
    repository = FileRepository(tmp_path)
    providers = _build_providers()

    collect_news_daily(NOW, repository, providers)

    details_dir = repository.daily_dir(BUSINESS_DATE) / "details"
    sina_files = sorted(
        name for name in (details_dir).glob("sina_news_*.txt")
    )
    assert [path.name for path in sina_files] == [
        "sina_news_sina_news_full.txt",
        "sina_news_sina_news_no_metric.txt",
        "sina_news_sina_news_short.txt",
    ]
    full_path = details_dir / "sina_news_sina_news_full.txt"
    assert full_path.read_text("utf-8") == _LONG_BODY
    short_path = details_dir / "sina_news_sina_news_short.txt"
    assert "一句话不够长" in short_path.read_text("utf-8")
    no_metric_path = details_dir / "sina_news_sina_news_no_metric.txt"
    assert no_metric_path.read_text("utf-8") == ""

    normalized = json.loads(
        (repository.daily_dir(BUSINESS_DATE) / "normalized" / "sina_news.json")
        .read_text("utf-8")
    )
    assert [row["item_id"] for row in normalized] == [
        "sina_news_full",
        "sina_news_short",
        "sina_news_no_metric",
    ]


def test_active_snapshot_published_only_after_eligible_and_rejected_exist(
    tmp_path, monkeypatch
):
    repository = FileRepository(tmp_path)
    providers = _build_providers()

    publish_calls: list[tuple[str, str]] = []
    original_publish = repository.publish_active_snapshot

    def tracking_publish(platform: str, business_date: Any) -> Any:
        day = repository.daily_dir(business_date)
        assert (day / "eligible" / f"{platform}.json").is_file(), (
            f"eligible missing for {platform} before publish"
        )
        assert (day / "rejected" / f"{platform}.json").is_file(), (
            f"rejected missing for {platform} before publish"
        )
        assert (day / "collection_status.json").is_file(), (
            "collection_status missing before publish"
        )
        publish_calls.append((platform, business_date))
        return original_publish(platform, business_date)

    monkeypatch.setattr(repository, "publish_active_snapshot", tracking_publish)

    collect_news_daily(NOW, repository, providers)

    assert publish_calls == [
        ("sina_news", BUSINESS_DATE),
        ("thepaper", BUSINESS_DATE),
        ("netease_news", BUSINESS_DATE),
    ]
    snapshot = json.loads(
        (tmp_path / "active_snapshots" / "sina_news.json").read_text("utf-8")
    )
    assert snapshot == {"business_date": BUSINESS_DATE}


def test_collection_uses_dynamic_floors_from_enriched_board(tmp_path):
    repository = FileRepository(tmp_path)
    full = _item(
        platform="sina_news",
        item_id="sina_news_full",
        rank=1,
        metrics={"top_num": 100.0, "comments": 100.0},
    )
    other = _item(
        platform="sina_news",
        item_id="sina_news_other",
        rank=2,
        metrics={"top_num": 50.0, "comments": 50.0},
    )
    detail_payload = ItemDetail(
        item_id="sina_news_full",
        content=_LONG_BODY,
        content_status="full_text",
        publication_time=None,
        collected_at=COLLECTED_AT,
        source_url="https://example.test/sina_news/sina_news_full",
        fetch_status="success",
    )
    other_detail = ItemDetail(
        item_id="sina_news_other",
        content="一句话不够长。",
        content_status="full_text",
        publication_time=None,
        collected_at=COLLECTED_AT,
        source_url="https://example.test/sina_news/sina_news_other",
        fetch_status="success",
    )
    provider = FakeNewsProvider(
        platform="sina_news",
        items=(full, other),
        detail_payloads={
            "sina_news_full": detail_payload,
            "sina_news_other": other_detail,
        },
    )
    provider.absolute_floors = {"comments": 200.0}

    collect_news_daily(NOW, repository, {"sina_news": provider})

    eligible = repository.load_eligible(BUSINESS_DATE, "sina_news")
    assert [item.hot_item.item_id for item in eligible] == ["sina_news_full"]


def test_collection_runs_with_three_workers_per_platform(tmp_path):
    repository = FileRepository(tmp_path)
    items = tuple(
        _item(
            platform="sina_news",
            item_id=f"sina_news_{index}",
            rank=index,
            metrics={"top_num": float(100 - index), "comments": float(index)},
        )
        for index in range(1, 7)
    )
    provider = FakeNewsProvider(platform="sina_news", items=items)

    collect_news_daily(NOW, repository, {"sina_news": provider})

    assert provider.max_active_details <= 3
    assert provider.max_active_details >= 2
