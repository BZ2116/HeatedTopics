"""Strict offline tests for the anonymous Baidu Hot Search provider."""

from pathlib import Path

import httpx
import pytest

from heated_topics_v3.contracts import (
    ContentValidation,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    QualifiedArticle,
)
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


# --- Task 3: supporting bodies and contextual search ---------------------------


def _board_item(title: str, hot_score: int, *, rank: int = 1) -> HotItem:
    from heated_topics_v3.providers.baidu_hot import _stable_event_id

    item_id = _stable_event_id(title)
    return HotItem(
        item_id=item_id,
        platform="baidu_hot",
        title=title,
        url=f"https://top.baidu.com/board?tab=realtime#{item_id}",
        rank=rank,
        heat=HeatMetrics(
            value=hot_score,
            label=str(hot_score),
            metric_name="hot_score",
            metrics={"hot_score": float(hot_score)},
        ),
        summary="",
        publication_time=None,
        collected_at=NOW,
        raw_payload={"query": title, "hotScore": str(hot_score)},
    )


def _qualified_baidu_event() -> QualifiedArticle:
    item = _board_item("人工智能手机发布", 987654, rank=1)
    evidence = HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=1,
        native_hot_value=987654.0,
        metrics={"hot_score": 987654.0},
        threshold_metrics={"hot_score": 1.0},
        qualified_by=("official_hot_board",),
    )
    detail = ItemDetail(
        item.item_id, "板块正文占位内容。", "full_text", None, NOW, item.url, "success"
    )
    validation = ContentValidation("accepted", "article", 100, 4, ())
    return QualifiedArticle(item, detail, evidence, validation, 987654.0)


def _search_article_client() -> httpx.Client:
    search_html = _fixture("baidu_search.html")
    article_html = _fixture("baidu_public_article.html")
    redirect = {
        "valid": "https://news.example.test/ai-phone",
        "unrelated": "https://sports.example.test/match",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "www.baidu.com" and path == "/s":
            return httpx.Response(200, text=search_html)
        if host == "www.baidu.com" and path == "/link":
            target = request.url.params.get("url", "")
            return httpx.Response(
                302, headers={"location": redirect.get(target, "https://www.baidu.com/s")}
            )
        if host == "news.example.test":
            return httpx.Response(200, text=article_html)
        if host == "sports.example.test":
            return httpx.Response(200, text="<article><p>比赛结果与球队积分排名。</p></article>")
        return httpx.Response(404, text="not found")

    return _client(handler)


def test_fetch_detail_uses_resolved_supporting_article_and_preserves_source():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    provider = BaiduHotProvider(_search_article_client())
    item = _board_item("人工智能手机发布", 987654)

    detail = provider.fetch_detail(item, NOW)

    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"
    assert detail.source_url == "https://news.example.test/ai-phone"
    assert "人工智能手机" in detail.content


def test_context_search_inherits_parent_event_evidence_without_board_refresh():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    parent = _qualified_baidu_event()
    provider = BaiduHotProvider(_search_article_client())

    capture = provider.search_with_context("人工智能", 1, 15, NOW, (parent,))

    assert len(capture.items) == 1
    item = capture.items[0]
    assert item.rank == parent.hot_item.rank
    assert item.heat.metrics == parent.hot_item.heat.metrics
    assert item.raw_payload["parent_event_id"] == parent.hot_item.item_id
    assert item.raw_payload["parent_event_title"] == parent.hot_item.title
    assert item.raw_payload["parent_rank"] == parent.hot_item.rank
    assert item.item_id != parent.hot_item.item_id
    assert item.item_id.startswith("baidu_hot_")


def test_search_with_context_without_official_articles_returns_empty():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    provider = BaiduHotProvider(_search_article_client())
    capture = provider.search_with_context("人工智能", 1, 15, NOW, ())
    assert capture.items == ()


def test_build_search_evidence_reflects_parent_hot_board_signal():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    parent = _qualified_baidu_event()
    provider = BaiduHotProvider(_search_article_client())
    capture = provider.search_with_context("人工智能", 1, 15, NOW, (parent,))
    item = capture.items[0]

    evidence = provider.build_search_evidence(item, {"hot_score": 1.0})

    assert evidence is not None
    assert evidence.source_kind == "official_hot_board"
    assert evidence.platform_rank == parent.hot_item.rank
    assert evidence.native_hot_value == 987654.0
    assert evidence.qualified_by == ("official_hot_board",)


def test_fetch_detail_rejects_captcha_search_page():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>百度安全验证 wappass.baidu.com</body></html>")

    provider = BaiduHotProvider(_client(handler))
    detail = provider.fetch_detail(_board_item("人工智能手机发布", 987654), NOW)
    assert detail.content_status == "rejected"


def test_fetch_detail_rejects_short_body():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    search_html = _fixture("baidu_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "www.baidu.com" and path == "/s":
            return httpx.Response(200, text=search_html)
        if host == "www.baidu.com" and path == "/link":
            return httpx.Response(302, headers={"location": "https://news.example.test/x"})
        if host == "news.example.test":
            return httpx.Response(200, text="<article><p>太短的正文。</p></article>")
        return httpx.Response(404)

    provider = BaiduHotProvider(_client(handler))
    detail = provider.fetch_detail(_board_item("人工智能手机发布", 987654), NOW)
    assert detail.content_status == "rejected"


def test_fetch_detail_rejects_baidu_aggregation_surface():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    search_html = _fixture("baidu_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "www.baidu.com" and path == "/s":
            return httpx.Response(200, text=search_html)
        if host == "www.baidu.com" and path == "/link":
            return httpx.Response(302, headers={"location": "https://www.baidu.com/s?wd=aggregate"})
        return httpx.Response(404)

    provider = BaiduHotProvider(_client(handler))
    detail = provider.fetch_detail(_board_item("人工智能手机发布", 987654), NOW)
    assert detail.content_status == "rejected"


def test_fetch_detail_handles_redirect_loop():
    from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

    search_html = _fixture("baidu_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "www.baidu.com" and path == "/s":
            return httpx.Response(200, text=search_html)
        if host == "www.baidu.com" and path == "/link":
            return httpx.Response(302, headers={"location": "https://www.baidu.com/link?url=loop"})
        return httpx.Response(404)

    provider = BaiduHotProvider(_client(handler))
    detail = provider.fetch_detail(_board_item("人工智能手机发布", 987654), NOW)
    assert detail.content_status == "rejected"
