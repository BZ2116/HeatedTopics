"""Tests for the DailyHotApi adapter provider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.dailyhot import DailyHotApiProvider


@pytest.fixture
def fake_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "dailyhot"
    cache.mkdir()
    (cache / "36kr.json").write_text(
        json.dumps(
            {
                "key": "dailyhot:36kr:today",
                "fetched_at": "2026-07-30T10:00:00+08:00",
                "data": [
                    {
                        "record": {
                            "id": "3865519682802948",
                            "platform": "36kr",
                            "title": "腾讯买出了AI半壁江山",
                            "url": "https://www.36kr.com/p/3865519682802948",
                            "rank": 1,
                            "hot_value": "56641",
                            "owner": "字母榜",
                            "category": "auxiliary_tech_business",
                        }
                    },
                    {
                        "record": {
                            "id": "3866428592657411",
                            "platform": "36kr",
                            "title": "8点1氪",
                            "url": "https://www.36kr.com/p/3866428592657411",
                            "rank": 2,
                            "hot_value": "29182",
                        }
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return cache


def test_collect_hot_list_reads_cache(fake_cache: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=fake_cache)
    capture = p.collect_hot_list("2026-07-30T10:00:00+08:00")
    assert len(capture.items) == 2
    first = capture.items[0]
    assert first.title == "腾讯买出了AI半壁江山"
    assert first.platform == "36kr"
    assert first.rank == 1
    assert first.url == "https://www.36kr.com/p/3865519682802948"
    assert first.item_id == "3865519682802948"
    assert first.heat.value == 56641


def test_collect_hot_list_returns_empty_when_cache_missing(tmp_path: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=tmp_path)
    capture = p.collect_hot_list("2026-07-30T10:00:00+08:00")
    assert capture.items == ()


def test_collect_hot_list_skips_records_missing_required_fields(tmp_path: Path) -> None:
    cache = tmp_path / "dailyhot"
    cache.mkdir()
    (cache / "junk.json").write_text(
        json.dumps(
            {
                "key": "dailyhot:junk:today",
                "data": [
                    {"record": {"id": "1", "title": "ok", "url": "https://x.com/1", "rank": 1}},
                    {"record": {"title": "no id", "url": "https://x.com/2", "rank": 2}},
                    {"record": {"id": "3", "url": "https://x.com/3", "rank": 3}},
                    {"record": {"id": "4", "title": "no url", "rank": 4}},
                ],
            }
        ),
        encoding="utf-8",
    )
    p = DailyHotApiProvider(platform="junk", cache_dir=cache)
    capture = p.collect_hot_list("2026-07-30T10:00:00+08:00")
    assert [it.item_id for it in capture.items] == ["1"]


def _make_item(url: str = "https://www.36kr.com/p/123") -> HotItem:
    return HotItem(
        item_id="123",
        platform="36kr",
        title="t",
        url=url,
        rank=1,
        heat=HeatMetrics(value=10, label="hot", metric_name="hot_value", metrics={}),
        summary="",
        publication_time=None,
        collected_at="2026-07-30T10:00:00+08:00",
    )


class _StubResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_fetch_detail_returns_title_only_when_gne_fails(tmp_path: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=tmp_path)

    class _StubClient:
        def get(self, url, *a, **kw):
            return _StubResponse(200, "<html><head></head><body>无正文</body></html>")

    p._client = _StubClient()  # type: ignore[assignment]
    detail = p.fetch_detail(_make_item(), "2026-07-30T10:00:00+08:00")
    assert detail.content_status in ("title_only", "full_text")
    assert detail.source_url == "https://www.36kr.com/p/123"


def test_fetch_detail_returns_full_text_when_gne_succeeds(tmp_path: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=tmp_path)
    long_body = "段落一。" + ("这是一段真实长度足够长的中文正文。" * 30)

    class _StubClient:
        def get(self, url, *a, **kw):
            return _StubResponse(200, f"<html><body><article>{long_body}</article></body></html>")

    p._client = _StubClient()  # type: ignore[assignment]
    detail = p.fetch_detail(_make_item(), "2026-07-30T10:00:00+08:00")
    assert detail.content_status == "full_text"
    assert "段落一" in detail.content


def test_fetch_detail_returns_title_only_on_http_failure(tmp_path: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=tmp_path)

    class _StubClient:
        def get(self, url, *a, **kw):
            return _StubResponse(500, "boom")

    p._client = _StubClient()  # type: ignore[assignment]
    detail = p.fetch_detail(_make_item(), "2026-07-30T10:00:00+08:00")
    assert detail.content_status == "title_only"
    assert detail.fetch_status.startswith("fetch_failed:")