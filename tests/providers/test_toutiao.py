import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.providers.toutiao import TOUTIAO_HOT_BOARD_URL, TOUTIAO_SEARCH_URL, ToutiaoProvider

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-13T04:00:00Z"


@pytest.mark.parametrize("operation", ["board", "search"])
def test_board_and_search_raise_for_http_errors(operation):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": "unavailable"})
        )
    )
    provider = ToutiaoProvider(client)

    with pytest.raises(httpx.HTTPStatusError):
        if operation == "board":
            provider.collect_hot_list(NOW)
        else:
            provider.search("AI", NOW)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "failure", "data": []},
        {"status": "success", "data": []},
    ],
)
def test_hot_board_rejects_malformed_error_and_empty_payloads(payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(ValueError):
        ToutiaoProvider(client).collect_hot_list(NOW)


@pytest.mark.parametrize("payload", [{}, {"status": "failure", "count": 0, "dom": ""}])
def test_search_rejects_malformed_and_api_error_payloads(payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(ValueError):
        ToutiaoProvider(client).search("AI", NOW)


@pytest.mark.parametrize("dom", ["", " \n\t"])
def test_search_accepts_explicit_zero_count_with_blank_dom_as_genuine_empty_result(dom):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"count": 0, "dom": dom})
        )
    )

    capture = ToutiaoProvider(client).search("no-such-current-topic", NOW)

    assert capture.items == ()


def test_search_rejects_zero_count_when_dom_is_not_empty():
    raw = json.dumps(
        {
            "count": 0,
            "dom": '<article data-group-id="9001"><h2>Unexpected card</h2></article>',
        }
    )

    with pytest.raises(ValueError):
        ToutiaoProvider.parse_search(raw, NOW)


@pytest.mark.parametrize("count", [False, 0.0, "0", None])
def test_search_rejects_legacy_empty_data_without_strict_integer_zero_count(count):
    payload = {"data": []}
    if count is not None:
        payload["count"] = count

    with pytest.raises(ValueError):
        ToutiaoProvider.parse_search(json.dumps(payload), NOW)


def test_search_rejects_nonempty_legacy_data_when_every_row_is_malformed():
    raw = json.dumps({"data": [{"unexpected": "shape"}]})

    with pytest.raises(ValueError):
        ToutiaoProvider.parse_search(raw, NOW)


def test_search_accepts_structurally_valid_legacy_rows_all_filtered_by_age():
    raw = json.dumps(
        {
            "data": [
                {
                    "id": "old-1",
                    "title": "Old but valid",
                    "url": "https://www.toutiao.com/article/old-1/",
                    "publish_time": "2026-07-10T03:00:00Z",
                }
            ]
        }
    )

    assert ToutiaoProvider.parse_search(raw, NOW) == ()

def test_collect_hot_list_preserves_raw_text_and_parses_heat():
    raw = (FIXTURES / "toutiao_hot_board.json").read_text(encoding="utf-8")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=raw)))
    capture = ToutiaoProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert capture.raw_text == raw and capture.raw_suffix == ".json"
    assert capture.items[0].heat.value == 98765
    assert capture.items[1].heat.value is None
    assert client.get(TOUTIAO_HOT_BOARD_URL).status_code == 200

def test_search_uses_exactly_one_keyword_and_parses_current_dom_cards():
    payload = json.loads((FIXTURES / "toutiao_search.json").read_text(encoding="utf-8"))
    payload["count"] = 777
    raw = json.dumps(payload)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=raw)
    capture = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(handler))).search("AI Agent", NOW)
    assert len(requests) == 1 and str(requests[0].url).startswith(TOUTIAO_SEARCH_URL)
    assert dict(requests[0].url.params) == {
        "keyword": "AI Agent",
        "pd": "information",
        "source": "search_subtab_switch",
        "from": "information",
        "format": "json",
        "count": "10",
        "offset": "0",
    }
    assert [item.item_id for item in capture.items] == [
        "toutiao_7661817657498305030",
        "toutiao_7661826133797487147",
    ]
    assert capture.items[0].title == "OpenAI 挖了苹果 400 人，到底在下一盘什么棋？"
    assert capture.items[0].url == "https://www.toutiao.com/group/7661817657498305030/"
    assert capture.items[0].summary.startswith("苹果与OpenAI的商业机密诉讼案")
    assert capture.items[0].publication_time == "1783905943"
    assert capture.items[0].raw_payload["group_id"] == "7661817657498305030"
    assert capture.items[0].raw_payload["source"] == "人人都是产品经理"
    for rank, item in enumerate(capture.items, 1):
        assert item.heat.metric_name == "search_rank"
        assert item.heat.value == rank
        assert item.heat.metrics == {"search_rank": rank}
        assert item.heat.value != payload["count"]


def test_search_dom_void_elements_do_not_leak_title_summary_or_source_scopes():
    raw = json.dumps({"count": 999, "dom": """
        <article data-group-id="9001">
          <a href="https://toutiao.com/group/9001/"><h2>Title<img src="cover.jpg"></h2></a>
          <p>Summary<br>continued</p>
          <footer><span class="source">Source<img src="avatar.jpg"></span><time datetime="1783905943">recent</time></footer>
        </article>
    """})
    item = ToutiaoProvider.parse_search(raw, NOW)[0]
    assert item.title == "Title"
    assert item.summary == "Summary continued"
    assert item.raw_payload["source"] == "Source"
    assert item.publication_time == "1783905943"


def test_search_keeps_legacy_data_rows_as_compatibility_fallback():
    raw = json.dumps({"count": 99, "data": [
        {"id": "201", "title": "Fresh agent story", "url": "https://www.toutiao.com/article/201/", "abstract": "Fresh summary", "publish_time": "2026-07-13T03:00:00Z", "read_count": 1200, "comment_count": 34},
        {"id": "202", "title": "Old agent story", "url": "https://www.toutiao.com/article/202/", "abstract": "Old summary", "publish_time": "2026-07-10T03:00:00Z"},
    ]})
    items = ToutiaoProvider.parse_search(raw, NOW)
    assert [item.item_id for item in items] == ["toutiao_201"]
    assert items[0].heat.metric_name == "engagement"
    assert items[0].heat.metrics == {"reads": 1200, "comments": 34}

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
