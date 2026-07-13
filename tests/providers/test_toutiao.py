import json
from dataclasses import replace
from pathlib import Path

import httpx

from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.providers.toutiao import TOUTIAO_HOT_BOARD_URL, TOUTIAO_SEARCH_URL, ToutiaoProvider

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-13T04:00:00Z"

def test_collect_hot_list_preserves_raw_text_and_parses_heat():
    raw = (FIXTURES / "toutiao_hot_board.json").read_text(encoding="utf-8")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=raw)))
    capture = ToutiaoProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert capture.raw_text == raw and capture.raw_suffix == ".json"
    assert capture.items[0].heat.value == 98765
    assert capture.items[1].heat.value is None
    assert client.get(TOUTIAO_HOT_BOARD_URL).status_code == 200

def test_search_uses_exactly_one_keyword_classifies_engagement_and_filters_old_rows():
    raw = (FIXTURES / "toutiao_search.json").read_text(encoding="utf-8")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=raw)
    capture = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(handler))).search("AI Agent", NOW)
    assert len(requests) == 1 and str(requests[0].url).startswith(TOUTIAO_SEARCH_URL)
    assert requests[0].url.params.get_list("keyword") == ["AI Agent"]
    assert [item.item_id for item in capture.items] == ["toutiao_201", "toutiao_203"]
    assert capture.items[0].heat.metric_name == "engagement"
    assert capture.items[0].heat.metrics == {"reads": 1200, "comments": 34}

def test_fetch_detail_fallback_order():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    provider = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))), rendered_fetcher=lambda url: "Rendered article")
    assert provider.fetch_detail(item, NOW).fetch_status == "success"
    provider = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))))
    detail = provider.fetch_detail(item, NOW)
    assert detail.content == item.summary and detail.fetch_status == "partial"

def test_search_treats_malformed_publication_time_as_undated():
    raw = json.dumps({"data": [{"id": "bad-date", "title": "Still useful", "url": "https://www.toutiao.com/article/204/", "publish_time": "not-a-date"}]})
    item = ToutiaoProvider.parse_search(raw, NOW)[0]
    assert item.title == "Still useful" and item.publication_time is None

def test_fetch_detail_uses_title_when_summary_and_pages_are_empty():
    item = replace(ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0], summary="")
    provider = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=""))), rendered_fetcher=lambda url: "")
    detail = provider.fetch_detail(item, NOW)
    assert detail.content == item.title and detail.content_status == "title_only"

def test_fetch_detail_continues_to_rendered_after_static_fetch_exception():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    detail = ToutiaoProvider(client, rendered_fetcher=lambda url: "Rendered recovery").fetch_detail(item, NOW)
    assert detail.content == "Rendered recovery" and detail.content_status == "full_text"

def test_fetch_detail_continues_to_summary_after_rendered_exception():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="")))
    def failed_render(url):
        raise RuntimeError("browser unavailable")
    detail = ToutiaoProvider(client, rendered_fetcher=failed_render).fetch_detail(item, NOW)
    assert detail.content == item.summary and detail.content_status == "summary"

def test_search_interprets_naive_timestamps_as_asia_shanghai_for_24_hour_filter():
    raw = json.dumps({"data": [
        {"id": "inside", "title": "Inside", "url": "https://www.toutiao.com/article/301/", "publish_time": "2026-07-12T12:01:00"},
        {"id": "outside", "title": "Outside", "url": "https://www.toutiao.com/article/302/", "publish_time": "2026-07-12T11:59:00"},
    ]})
    items = ToutiaoProvider.parse_search(raw, NOW)
    assert [item.item_id for item in items] == ["toutiao_inside"]
