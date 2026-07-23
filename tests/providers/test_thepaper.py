"""Strict offline tests for the anonymous The Paper provider."""
import json
from pathlib import Path

import httpx
import pytest

from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.providers.thepaper import (
    THEPAPER_ARTICLE_URL,
    THEPAPER_HOT_URL,
    THEPAPER_SEARCH_URL,
    ThePaperProvider,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-23T04:00:00Z"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures():
    return {
        "hot": _fixture("thepaper_hot.json"),
        "search": _fixture("thepaper_search.json"),
        "article": _fixture("thepaper_article.html"),
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _hot_item() -> HotItem:
    return ThePaperProvider.parse_hot_list(_fixture("thepaper_hot.json"), NOW)[0]


def _article_url(cont_id: str) -> str:
    return ThePaperProvider._article_url(cont_id)  # noqa: SLF001 - test only


def test_hot_list_keeps_articles_and_strips_video_paywall_external(fixtures):
    items = ThePaperProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items
    assert all(item.raw_payload["contType"] == 0 for item in items)
    assert all(item.raw_payload.get("paywalled") is False for item in items)
    assert all("newsDetail_forward_" in item.url for item in items)


def test_hot_list_first_item_keeps_interaction_and_praise(fixtures):
    items = ThePaperProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items[0].platform == "thepaper"
    assert items[0].rank == 1
    assert items[0].heat.metrics == {
        "interaction_num": 15,
        "praise_times": 396,
    }
    assert items[0].heat.metric_name == "interaction_num"


def test_collect_hot_list_hits_official_endpoint_and_keeps_capture(fixtures):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=fixtures["hot"])

    client = _client(handler)
    capture = ThePaperProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert str(seen[0].url) == THEPAPER_HOT_URL
    assert capture.items[0].heat.metrics == {
        "interaction_num": 15,
        "praise_times": 396,
    }


def test_search_sends_exact_anonymous_post_contract():
    raw = _fixture("thepaper_search.json")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=raw)

    capture = ThePaperProvider(_client(handler)).search(
        "人工智能", 1, 15, NOW
    )
    assert isinstance(capture, ProviderCapture)
    request = seen[0]
    assert str(request.url) == THEPAPER_SEARCH_URL
    assert request.method == "POST"
    assert request.headers["client-type"] == "1"
    assert request.headers["content-type"].startswith("application/json")
    payload = json.loads(request.content)
    assert payload == {
        "word": "人工智能",
        "orderType": 3,
        "pageNum": 1,
        "pageSize": 15,
        "searchType": 1,
    }
    assert capture.items


def test_search_strips_font_highlighting(fixtures):
    items = ThePaperProvider.parse_search(fixtures["search"], NOW)
    assert items
    for item in items:
        assert "<font" not in item.title
        assert "</font>" not in item.title
        assert "<font" not in item.summary


def test_search_filters_external_paywalled_and_paywall_rows(fixtures):
    items = ThePaperProvider.parse_search(fixtures["search"], NOW)
    cont_ids = {item.raw_payload["contId"] for item in items}
    assert "3100003" not in cont_ids  # external forward
    assert "3100004" not in cont_ids  # paywalled
    assert all(item.raw_payload["contType"] == 0 for item in items)
    assert all(item.raw_payload.get("paywalled") is False for item in items)


def test_search_items_preserve_both_metrics(fixtures):
    items = ThePaperProvider.parse_search(fixtures["search"], NOW)
    first = items[0]
    assert first.heat.metrics == {
        "interaction_num": 45,
        "praise_times": 320,
    }
    assert first.heat.metric_name == "interaction_num"


def test_article_url_format_uses_news_detail_forward():
    assert _article_url("3000001") == THEPAPER_ARTICLE_URL.format(cont_id="3000001")


def test_fetch_detail_extracts_full_text_from_next_data():
    html = _fixture("thepaper_article.html")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    detail = ThePaperProvider(_client(handler)).fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"
    assert "正文第一段" in detail.content
    assert detail.content.count("正文第") >= 3


def test_fetch_detail_rejects_short_or_empty_body():
    html = "<!DOCTYPE html><html><body><div id='__NEXT_DATA__'></div></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    detail = ThePaperProvider(_client(handler)).fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "rejected"
    assert detail.content == ""
    assert detail.fetch_status.startswith("rejected:")
    assert "too_short" in detail.fetch_status


def test_enrich_metrics_is_noop():
    item = _hot_item()
    provider = ThePaperProvider(_client(lambda r: httpx.Response(200, text="{}")))
    enriched = provider.enrich_metrics(item, NOW)
    assert enriched == item


def test_enrich_metrics_noop_for_search_items(fixtures):
    items = ThePaperProvider.parse_search(fixtures["search"], NOW)
    provider = ThePaperProvider(_client(lambda r: httpx.Response(200, text="{}")))
    enriched = provider.enrich_metrics(items, NOW)
    assert enriched == items


def test_parse_hot_list_rejects_non_dict_or_missing_data():
    with pytest.raises(Exception):
        ThePaperProvider.parse_hot_list("{}", NOW)