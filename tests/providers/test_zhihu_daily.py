"""Strict offline tests for the anonymous Zhihu Daily provider."""

from datetime import datetime, timedelta, timezone
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


# --- Task 5: seven-day archive search -----------------------------------------


def _archive_client() -> tuple[httpx.Client, list[int]]:
    day1 = _fixture("zhihu_daily_before_20260722.json")
    day2 = _fixture("zhihu_daily_before_20260721.json")
    counter: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        path = request.url.path
        if path == "/api/4/news/before/20260722":
            return httpx.Response(200, text=day1)
        if path == "/api/4/news/before/20260721":
            return httpx.Response(200, text=day2)
        if path.startswith("/api/4/news/before/"):
            return httpx.Response(200, text='{"date": "0", "stories": []}')
        return httpx.Response(404)

    return _client(handler), counter


def test_archive_search_scans_seven_days_once_and_pages_cached_matches():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    client, counter = _archive_client()
    provider = ZhihuDailyProvider(client)

    first = provider.search("人工智能", 1, 15, NOW)
    second = provider.search("人工智能", 2, 15, NOW)

    combined = first.items + second.items
    assert combined
    assert all("人工智能" in item.title or "人工智能" in item.summary for item in combined)
    assert len({item.item_id for item in combined}) == len(combined)
    assert sum(counter) == 7


def test_archive_search_caps_unique_items_at_60():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    stories = ",".join(
        f'{{"id": {i}, "title": "人工智能故事 {i}", "hint": "h", "type": 0, "url": "https://daily.zhihu.com/story/{i}"}}'
        for i in range(80)
    )
    payload = '{"date": "20260722", "stories": [' + stories + "]}"
    counter: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        if request.url.path.startswith("/api/4/news/before/"):
            return httpx.Response(200, text=payload)
        return httpx.Response(404)

    provider = ZhihuDailyProvider(_client(handler))
    capture = provider.search("人工智能", 1, 60, NOW)
    assert sum(counter) == 7
    assert len(capture.items) == 60


def test_archive_search_does_not_succeed_on_http_or_schema_failure():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = ZhihuDailyProvider(_client(handler))
    capture = provider.search("人工智能", 1, 15, NOW)
    assert capture.items == ()


def _archive_article(date: str, story_id: int, rank: int):
    from heated_topics_v3.contracts import ContentValidation, ItemDetail, QualifiedArticle

    item = HotItem(
        item_id=f"zhihu_daily_{story_id}",
        platform="zhihu_daily",
        title="人工智能故事",
        url=f"https://daily.zhihu.com/story/{story_id}",
        rank=rank,
        heat=__import__("heated_topics_v3.contracts", fromlist=["HeatMetrics"]).HeatMetrics(
            None, "", "rank", {}
        ),
        summary="",
        publication_time=None,
        collected_at=NOW,
        raw_payload={
            "recommendation_date": date,
            "official_recommendation": True,
            "story_id": story_id,
        },
    )
    evidence = __import__("heated_topics_v3.contracts", fromlist=["HeatEvidence"]).HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=rank,
        native_hot_value=None,
        metrics={},
        threshold_metrics={},
        qualified_by=("official_hot_board",),
    )
    detail = ItemDetail(
        item.item_id, "正文占位。", "full_text", None, NOW, item.url, "success"
    )
    validation = ContentValidation("accepted", "zhihu_dom", 100, 4, ())
    return QualifiedArticle(item, detail, evidence, validation, 0.0)


def test_archive_search_evidence_requires_official_archive_markers():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    provider = ZhihuDailyProvider(_client(lambda r: httpx.Response(404)))

    article = _archive_article("20260722", 2001, 1)
    evidence = provider.build_search_evidence(article.hot_item, {})
    assert evidence is not None
    assert evidence.source_kind == "official_hot_board"
    assert evidence.platform_rank == 1

    item_no_rank = __import__("dataclasses").replace(article.hot_item, rank=None)
    assert provider.build_search_evidence(item_no_rank, {}) is None

    item_no_flag = __import__("dataclasses").replace(
        article.hot_item,
        raw_payload={**article.hot_item.raw_payload, "official_recommendation": False},
    )
    assert provider.build_search_evidence(item_no_flag, {}) is None

    item_no_date = __import__("dataclasses").replace(
        article.hot_item,
        raw_payload={k: v for k, v in article.hot_item.raw_payload.items() if k != "recommendation_date"},
    )
    assert provider.build_search_evidence(item_no_date, {}) is None


def test_rank_articles_orders_newest_date_first_then_rank():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    provider = ZhihuDailyProvider(_client(lambda r: httpx.Response(404)))
    newest_high_rank = _archive_article("20260722", 2001, 3)
    older_low_rank = _archive_article("20260721", 2004, 1)
    ordered = provider.rank_articles([older_low_rank, newest_high_rank])
    assert [a.hot_item.raw_payload["recommendation_date"] for a in ordered] == [
        "20260722",
        "20260721",
    ]
