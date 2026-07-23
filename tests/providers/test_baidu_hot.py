"""Strict offline tests for the anonymous Baidu Hot Search provider."""

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


def test_parse_hot_list_preserves_rank_hot_score_and_event_provenance():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    raw = _fixture("baidu_hot_board.html")
    items = BaiduHotProvider.parse_hot_list(raw, NOW)

    assert [item.rank for item in items] == [1, 2]
    assert [item.heat.value for item in items] == [987654, 456789]
    assert items[0].heat.metrics == {"hot_score": 987654}
    assert items[0].heat.metric_name == "hot_score"
    assert items[0].title == "人工智能手机发布"
    assert items[0].summary == "新产品和行业变化引发讨论"
    assert items[0].raw_payload["rawUrl"].endswith("/ai-phone")
    assert items[0].item_id.startswith("baidu_hot_")
    assert items[0].item_id != items[1].item_id


def test_parse_hot_list_accepts_alternate_top_level_envelope():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    raw = (
        "<!doctype html><body>"
        "<!--s-data:{\"cards\":[{\"content\":["
        "{\"index\":1,\"word\":\"备用事件\",\"query\":\"备用事件\","
        "\"hotScore\":\"100\",\"rawUrl\":\"https://example.test/x\"}"
        "]}]}-->"
    )
    items = BaiduHotProvider.parse_hot_list(raw, NOW)
    assert len(items) == 1
    assert items[0].rank == 1
    assert items[0].heat.value == 100


@pytest.mark.parametrize(
    "raw",
    [
        "<!doctype html><body>no marker here</body>",
        "<!doctype html><body><!--s-data:not-json--></body>",
        "<!doctype html><body><!--s-data:{\"data\":{\"cards\":[]}}--></body>",
        "<!doctype html><body><!--s-data:{\"data\":{\"cards\":[{}]}}--></body>",
        "<!doctype html><body><!--s-data:{\"data\":{\"cards\":[{\"content\":[]}]}}--></body>",
    ],
)
def test_parse_hot_list_fails_closed_on_malformed_boards(raw):
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    with pytest.raises(ProviderContractError):
        BaiduHotProvider.parse_hot_list(raw, NOW)


def test_parse_hot_list_skips_rows_without_title_or_query():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    raw = (
        '<!doctype html><body>'
        '<!--s-data:{"data":{"cards":[{"content":['
        '{"index":1,"rawUrl":"https://example.test/empty","hotScore":"10"},'
        '{"index":2,"word":"valid event","query":"valid event",'
        '"hotScore":"200","rawUrl":"https://example.test/ok"}'
        "]}]}}-->"
    )
    items = BaiduHotProvider.parse_hot_list(raw, NOW)
    assert [item.title for item in items] == ["valid event"]
    assert items[0].rank == 1


def test_collect_hot_list_raises_on_http_5xx():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    client = _client(lambda r: httpx.Response(503, text="boom"))
    with pytest.raises(httpx.HTTPStatusError):
        BaiduHotProvider(client).collect_hot_list(NOW)


def test_collect_hot_list_returns_provider_capture_with_items():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    raw = _fixture("baidu_hot_board.html")
    client = _client(lambda r: httpx.Response(200, text=raw))
    capture = BaiduHotProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert capture.raw_suffix == ".html"
    assert capture.raw_text == raw
    assert capture.items[0].title == "人工智能手机发布"
