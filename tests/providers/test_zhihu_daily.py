"""Strict offline tests for the anonymous Zhihu Daily provider."""

from pathlib import Path

import httpx
import pytest

from heated_topics_v3.contracts import HotItem
from heated_topics_v3.providers.common import ProviderCapture, ProviderContractError

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-23T04:00:00Z"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _latest_and_detail_client() -> httpx.Client:
    latest = _fixture("zhihu_daily_latest.json")
    detail = _fixture("zhihu_daily_detail.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/4/news/latest":
            return httpx.Response(200, text=latest)
        if path == "/api/4/news/1001":
            return httpx.Response(200, text=detail)
        return httpx.Response(404, text="not found")

    return _client(handler)


def _latest_item() -> HotItem:
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    items = ZhihuDailyProvider.parse_latest(_fixture("zhihu_daily_latest.json"), NOW)
    return items[0]


def test_latest_keeps_type_zero_and_uses_official_rank_only():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    items = ZhihuDailyProvider.parse_latest(_fixture("zhihu_daily_latest.json"), NOW)
    assert len(items) == 1
    assert items[0].item_id == "zhihu_daily_1001"
    assert items[0].rank == 1
    assert items[0].heat.value is None
    assert items[0].heat.metrics == {}
    assert items[0].raw_payload["recommendation_date"] == "20260723"


def test_detail_api_body_is_clean_full_text():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    provider = ZhihuDailyProvider(_latest_and_detail_client())
    detail = provider.fetch_detail(_latest_item(), NOW)
    assert detail.content_status == "full_text"
    assert detail.source_url == "https://daily.zhihu.com/story/1001"
    assert "<p>" not in detail.content
    assert detail.content.count("\n") >= 1


def test_build_board_evidence_uses_rank_only():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    provider = ZhihuDailyProvider(_latest_and_detail_client())
    evidence = provider.build_board_evidence(_latest_item(), {})
    assert evidence is not None
    assert evidence.source_kind == "official_hot_board"
    assert evidence.platform_rank == 1
    assert evidence.native_hot_value is None
    assert evidence.metrics == {}
    assert evidence.qualified_by == ("official_hot_board",)


def test_collect_hot_list_returns_capture_with_type_zero_items():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    capture = ZhihuDailyProvider(_latest_and_detail_client()).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert capture.raw_suffix == ".json"
    assert [item.item_id for item in capture.items] == ["zhihu_daily_1001"]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"date": "20260723", "stories": []}',
        '{"date": "20260723", "stories": [{"id": 5, "type": 1, "title": "视频"}]}',
    ],
)
def test_parse_latest_fails_closed(raw):
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    with pytest.raises(ProviderContractError):
        ZhihuDailyProvider.parse_latest(raw, NOW)


def test_fetch_detail_rejects_missing_body():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/4/news/1001":
            return httpx.Response(200, text='{"id": 1001, "title": "人工智能", "share_url": "https://daily.zhihu.com/story/1001"}')
        return httpx.Response(404)

    provider = ZhihuDailyProvider(_client(handler))
    detail = provider.fetch_detail(_latest_item(), NOW)
    assert detail.content_status == "rejected"


def test_fetch_detail_rejects_title_only_body():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/4/news/1001":
            return httpx.Response(
                200,
                text='{"id": 1001, "title": "人工智能工具如何改变内容创作", "share_url": "https://daily.zhihu.com/story/1001", "body": "<p>人工智能工具如何改变内容创作</p>"}',
            )
        return httpx.Response(404)

    provider = ZhihuDailyProvider(_client(handler))
    detail = provider.fetch_detail(_latest_item(), NOW)
    assert detail.content_status == "rejected"


def test_collect_hot_list_raises_on_http_503():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    client = _client(lambda r: httpx.Response(503, text="boom"))
    with pytest.raises(httpx.HTTPStatusError):
        ZhihuDailyProvider(client).collect_hot_list(NOW)
