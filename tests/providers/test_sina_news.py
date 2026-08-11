"""Strict offline tests for the anonymous Sina News provider."""
from pathlib import Path

import httpx
import pytest

from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.common import ProviderCapture, ProviderContractError
from heated_topics_v3.providers.sina_news import (
    SINA_COMMENT_URL,
    SINA_HOT_URL,
    SINA_SEARCH_URL,
    SinaNewsProvider,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-23T04:00:00Z"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures():
    return {
        "hot": _fixture("sina_news_hot.txt"),
        "search": _fixture("sina_news_search.json"),
    }


def _hot_item() -> HotItem:
    return SinaNewsProvider.parse_hot_list(_fixture("sina_news_hot.txt"), NOW)[0]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_hot_list_preserves_top_num_rank_and_comment_identity(fixtures):
    items = SinaNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items[0].platform == "sina_news"
    assert items[0].rank == 1
    assert items[0].heat.metrics["top_num"] == 15558
    assert items[0].raw_payload["commentid"]


def test_hot_list_normalizes_comma_formatted_top_num(fixtures):
    items = SinaNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items[0].heat.value == 15558
    assert items[1].heat.metrics["top_num"] == 9231


@pytest.mark.parametrize(
    "raw",
    [
        "var data = {};",
        "var data = {\"data\": {}};",
        "var data = {\"data\": []};",
        "not a jsonp payload",
    ],
)
def test_hot_list_rejects_missing_or_non_list_data(raw):
    with pytest.raises(ProviderContractError):
        SinaNewsProvider.parse_hot_list(raw, NOW)


def test_collect_hot_list_hits_official_endpoint_and_keeps_capture():
    raw = _fixture("sina_news_hot.txt")
    seen = []
    client = _client(lambda r: (seen.append(r), httpx.Response(200, text=raw))[1])
    capture = SinaNewsProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert capture.raw_text == raw
    assert str(seen[0].url) == SINA_HOT_URL
    assert capture.items[0].heat.metrics["top_num"] == 15558


def test_search_count_is_not_heat(fixtures):
    items = SinaNewsProvider.parse_search(fixtures["search"], NOW)
    assert items
    assert all(item.heat.value is None for item in items)
    assert all("search_rank" not in item.heat.metrics for item in items)


def test_search_only_sends_query_and_page():
    raw = _fixture("sina_news_search.json")
    seen = []
    client = _client(lambda r: (seen.append(r), httpx.Response(200, text=raw))[1])
    capture = SinaNewsProvider(client).search("经济数据", NOW)
    assert isinstance(capture, ProviderCapture)
    assert str(seen[0].url).startswith(SINA_SEARCH_URL)
    assert dict(seen[0].url.params) == {"q": "经济数据", "page": "1"}
    assert all(item.platform == "sina_news" for item in capture.items)


def test_article_requires_validated_full_text():
    html = _fixture("sina_news_article.html")
    detail = SinaNewsProvider(_client(lambda r: httpx.Response(200, text=html))).fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"
    assert detail.content


def test_short_article_is_rejected_not_summary_fallback():
    html = _fixture("sina_news_article_short.html")
    detail = SinaNewsProvider(_client(lambda r: httpx.Response(200, text=html))).fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content == ""
    assert detail.content_status == "rejected"
    assert detail.fetch_status == "rejected:too_short"


def test_enrich_metrics_adds_public_comment_total():
    comments = _fixture("sina_news_comments.json")
    seen = []
    client = _client(lambda r: (seen.append(r), httpx.Response(200, text=comments))[1])
    enriched = SinaNewsProvider(client).enrich_metrics([_hot_item()], NOW)
    assert str(seen[0].url).startswith(SINA_COMMENT_URL)
    params = dict(seen[0].url.params)
    assert params["channel"] == "gn"
    assert params["newsid"] == "comos-aaa11111"
    assert enriched[0].heat.metrics["comments"] == 4821
    assert enriched[0].heat.metrics["top_num"] == 15558


def test_enrich_metrics_never_invents_zero_on_malformed_response():
    client = _client(lambda r: httpx.Response(200, text="not json"))
    enriched = SinaNewsProvider(client).enrich_metrics([_hot_item()], NOW)
    assert "comments" not in enriched[0].heat.metrics

    client = _client(lambda r: httpx.Response(500, text="boom"))
    enriched = SinaNewsProvider(client).enrich_metrics([_hot_item()], NOW)
    assert "comments" not in enriched[0].heat.metrics


def test_enrich_metrics_returns_tuple_of_n_items_for_sequence_input(fixtures):
    comments = _fixture("sina_news_comments.json")
    client = _client(lambda r: httpx.Response(200, text=comments))
    items = SinaNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    enriched = SinaNewsProvider(client).enrich_metrics(items, NOW)
    assert isinstance(enriched, tuple)
    assert len(enriched) == len(items)
    assert {item.item_id for item in enriched} == {item.item_id for item in items}


def test_enrich_metrics_preserves_item_when_comment_call_fails():
    seen: list[str] = []
    items = (
        HotItem(
            item_id="sina_news_a",
            platform="sina_news",
            title="无 commentid 的标题",
            url="https://news.sina.com.cn/a",
            rank=1,
            heat=HeatMetrics(10, "10", "top_num", {"top_num": 10}),
            summary="示例摘要",
            publication_time=None,
            collected_at=NOW,
            raw_payload={"commentid": ""},
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(500, text="boom")

    enriched = SinaNewsProvider(_client(handler)).enrich_metrics(items, NOW)
    assert enriched == items
    assert "comments" not in enriched[0].heat.metrics
    assert seen == []
