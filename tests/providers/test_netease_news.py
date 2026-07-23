"""Strict offline tests for the anonymous NetEase News provider."""
from pathlib import Path

import httpx
import pytest

from heated_topics_v3.contracts import HotItem
from heated_topics_v3.providers.common import ProviderCapture, ProviderContractError
from heated_topics_v3.providers.netease_news import (
    NETEASE_ARTICLE_URL,
    NETEASE_HOT_URL,
    NETEASE_SEARCH_URL,
    NeteaseNewsProvider,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-23T04:00:00Z"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures():
    return {
        "hot": _fixture("netease_news_hot.json"),
        "search": _fixture("netease_news_search.html"),
        "article": _fixture("netease_news_article.html"),
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _hot_item() -> HotItem:
    return NeteaseNewsProvider.parse_hot_list(
        _fixture("netease_news_hot.json"), NOW
    )[0]


def _article_url(docid: str) -> str:
    return NETEASE_ARTICLE_URL.format(docid=docid)


def test_uses_rich_hot_endpoint_and_preserves_all_metrics(fixtures):
    items = NeteaseNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items[0].platform == "netease_news"
    assert items[0].rank == 1
    assert items[0].heat.metrics == {
        "hot_value": 2478683,
        "click": 835915,
        "comments": 74959,
        "votes": 65567,
        "thread_votes": 1436,
    }
    assert all(item.raw_payload["type"] == "doc" for item in items)


def test_hot_list_drops_video_rows_and_keeps_doc_items(fixtures):
    items = NeteaseNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    docids = {item.raw_payload["contentId"] for item in items}
    assert "JC0VID001" not in docids
    assert "JC0ABC001" in docids


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"code": 1}',
        '{"code": 0, "data": {}}',
        '{"code": 0, "data": {"items": []}}',
    ],
)
def test_hot_list_rejects_non_success_or_empty(raw):
    with pytest.raises(ProviderContractError):
        NeteaseNewsProvider.parse_hot_list(raw, NOW)


def test_collect_hot_list_hits_official_endpoint_and_keeps_capture():
    raw = _fixture("netease_news_hot.json")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=raw)

    client = _client(handler)
    capture = NeteaseNewsProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert str(seen[0].url) == NETEASE_HOT_URL
    assert capture.items[0].heat.metrics["hot_value"] == 2478683


def test_search_returns_fifty_unique_candidates_without_treating_order_as_heat(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    # 50 fixture cards minus 1 video + 1 malformed url = 48 after strict filters.
    assert len(items) == 48
    assert items[0].heat.metrics == {"comments": 2}
    assert items[0].heat.metric_name == "public_engagement"


def test_search_filters_video_and_malformed_external_urls(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    urls = [item.url for item in items]
    assert not any("v.163.com" in url for url in urls)
    assert not any("malformed-url.example.com" in url for url in urls)


def test_search_strips_em_keyword_highlighting(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    for item in items:
        assert "<em>" not in item.title
        assert "</em>" not in item.title


def test_search_normalizes_zero_comment_rows(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    zero_items = [item for item in items if item.heat.metrics.get("comments") == 0]
    assert zero_items
    assert all(item.heat.value == 0 for item in zero_items)


def test_search_deduplicates_repeated_docids(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    docids = [item.raw_payload["docid"] for item in items]
    assert len(docids) == len(set(docids))


def test_search_only_sends_keyword_query_param():
    raw = _fixture("netease_news_search.html")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=raw)

    capture = NeteaseNewsProvider(_client(handler)).search("人工智能", NOW)
    assert isinstance(capture, ProviderCapture)
    assert str(seen[0].url).startswith(NETEASE_SEARCH_URL)
    assert dict(seen[0].url.params) == {"keyword": "人工智能"}


def test_article_url_format_uses_dy_article_path():
    assert _article_url("JC0ABC001") == NETEASE_ARTICLE_URL.format(
        docid="JC0ABC001"
    )


def test_post_body_is_full_text_and_non_doc_is_rejected(fixtures):
    detail = NeteaseNewsProvider(
        _client(lambda r: httpx.Response(200, text=fixtures["article"]))
    ).fetch_detail(_hot_item(), NOW)
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"
    assert "示例通讯社" in detail.content


def test_short_article_is_rejected_not_summary_fallback():
    html = "<html><body><div class='post_body'>短</div></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    detail = NeteaseNewsProvider(_client(handler)).fetch_detail(_hot_item(), NOW)
    assert detail.content == ""
    assert detail.content_status == "rejected"
    assert detail.fetch_status.startswith("rejected:")


def test_enrich_metrics_keeps_search_comment_count(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    provider = NeteaseNewsProvider(
        _client(lambda r: httpx.Response(200, text="{}"))
    )
    enriched = provider.enrich_metrics(items, NOW)
    assert enriched[0].heat.metrics["comments"] == 2


def test_enrich_metrics_never_invents_zero_on_malformed_response():
    items = (_hot_item(),)
    provider = NeteaseNewsProvider(
        _client(lambda r: httpx.Response(200, text="not json"))
    )
    enriched = provider.enrich_metrics(items, NOW)
    assert enriched == items


def test_parse_hot_list_requires_doc_type():
    raw = (
        '{"code": 0, "data": {"items": [{"contentId": "X", "type": "video"}]}}'
    )
    with pytest.raises(ProviderContractError):
        NeteaseNewsProvider.parse_hot_list(raw, NOW)