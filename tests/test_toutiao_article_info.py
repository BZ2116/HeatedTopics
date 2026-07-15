import json
from pathlib import Path

import pytest

from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.toutiao import (
    TOUTIAO_ARTICLE_INFO_URL,
    attach_article_heat_fields,
    compute_article_heat,
    extract_toutiao_article_id,
    fetch_toutiao_article_info,
    fetch_toutiao_item_details,
    fetch_toutiao_search_pages,
)


def _search_hot_item(url: str, rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"toutiao_search_{rank}",
        platform="toutiao",
        item_type="search_result",
        title=f"Search Result {rank}",
        url=url,
        rank=rank,
        heat=HeatMetrics(value=100, label="100", metric_name="search_engagement", metrics={}),
        summary="summary",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={"search_phrase": "AI工具", "source_kind": "search_result"},
    )


def _hot_board_item(url: str, hot_value: int, rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"toutiao_{rank}",
        platform="toutiao",
        item_type="topic",
        title=f"Hot Board {rank}",
        url=url,
        rank=rank,
        heat=HeatMetrics(
            value=hot_value, label=str(hot_value), metric_name="hot_value",
            metrics={"hot_value": hot_value},
        ),
        summary="",
        category="",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={"ClusterId": str(rank), "source_kind": "hot_board"},
    )


def test_extract_toutiao_article_id_handles_common_patterns():
    assert extract_toutiao_article_id("https://www.toutiao.com/group/1234567890/") == "1234567890"
    assert extract_toutiao_article_id("https://www.toutiao.com/article/7654321/?x=1") == "7654321"
    assert extract_toutiao_article_id("https://www.toutiao.com/trending/9999/") == "9999"
    assert extract_toutiao_article_id("https://so.toutiao.com/search/jump?url=...&groupid=42") == "42"
    assert extract_toutiao_article_id("") is None
    assert extract_toutiao_article_id("https://example.com/no-id") is None


def test_compute_article_heat_uses_documented_weights():
    metrics = {
        "impression_count": 100,
        "digg_count": 50,
        "comment_count": 10,
        "repost_count": 5,
        "repin_count": 20,
    }
    expected = 100 * 1 + 50 * 2 + 10 * 5 + 5 * 10 + 20 * 3
    assert compute_article_heat(metrics) == expected


def test_compute_article_heat_handles_missing_keys():
    assert compute_article_heat({}) == 0
    assert compute_article_heat({"comment_count": 7}) == 7 * 5
    assert compute_article_heat({"comment_count": None, "digg_count": 3}) == 3 * 2


def test_fetch_toutiao_article_info_uses_correct_url_and_parses_data():
    captured: list[str] = []

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        captured.append(url)
        return json.dumps(
            {
                "data": {
                    "impression_count": 200,
                    "digg_count": 30,
                    "comment_count": 5,
                    "repost_count": 1,
                    "repin_count": 2,
                    "is_toutiao_hot": True,
                    "is_original": False,
                    "content": "<p>hello</p>",
                }
            }
        )

    info = fetch_toutiao_article_info("12345", fetcher=fake_fetcher)
    assert captured == [TOUTIAO_ARTICLE_INFO_URL.format(article_id="12345")]
    assert info is not None
    assert info["comment_count"] == 5
    assert info["is_toutiao_hot"] is True


def test_fetch_toutiao_article_info_returns_none_on_bad_payload():
    def fake_fetcher(_url: str, _t: int) -> str:
        return "not json"

    assert fetch_toutiao_article_info("1", fetcher=fake_fetcher) is None


def test_attach_article_heat_fields_for_search_item_replaces_hot_value():
    item = _search_hot_item("https://www.toutiao.com/group/12345/")
    info = {
        "impression_count": 100,
        "digg_count": 20,
        "comment_count": 5,
        "repost_count": 0,
        "repin_count": 1,
        "is_toutiao_hot": True,
        "is_original": False,
        "title": "中央财经大学2027年校园招聘公告",
    }
    expected_heat = 100 + 40 + 25 + 0 + 3

    enriched = attach_article_heat_fields(item, info)
    assert enriched.heat.value == expected_heat
    assert enriched.heat.metric_name == "article_heat"
    assert enriched.raw_payload["article_heat"] == expected_heat
    assert enriched.raw_payload["is_toutiao_hot"] is True
    assert enriched.raw_payload["article_info_status"] == "ok"
    assert enriched.raw_payload["source_kind"] == "article_info"
    assert enriched.raw_payload["article_title"] == "中央财经大学2027年校园招聘公告"


def test_attach_article_heat_fields_handles_missing_title():
    item = _search_hot_item("https://www.toutiao.com/group/12345/")
    info = {
        "impression_count": 100,
        "digg_count": 20,
        "comment_count": 5,
        "repost_count": 0,
        "repin_count": 1,
    }
    enriched = attach_article_heat_fields(item, info)
    assert enriched.raw_payload["article_title"] == ""


def test_attach_article_heat_fields_for_hot_board_preserves_hot_value():
    item = _hot_board_item("https://www.toutiao.com/group/99/", hot_value=5_000_000, rank=3)
    info = {
        "impression_count": 200,
        "digg_count": 10,
        "comment_count": 0,
        "repost_count": 0,
        "repin_count": 0,
        "is_toutiao_hot": True,
        "title": "马兴瑞被双开",
    }

    enriched = attach_article_heat_fields(item, info)
    assert enriched.heat.value == 5_000_000  # HotValue preserved
    assert enriched.heat.metric_name == "hot_value"
    assert enriched.raw_payload["article_heat"] == 200 + 20
    assert enriched.raw_payload["metric_name"] == "hot_value+article_heat"
    assert enriched.raw_payload["is_toutiao_hot"] is True
    assert enriched.raw_payload["article_title"] == "马兴瑞被双开"


def test_attach_article_heat_fields_handles_none_info():
    item = _search_hot_item("https://www.toutiao.com/group/55/")
    enriched = attach_article_heat_fields(item, None)
    assert enriched.raw_payload["article_info_status"] == "fetch_failed"
    assert "article_heat" not in enriched.raw_payload


def test_fetch_toutiao_search_pages_dedupes_across_pages(tmp_path: Path):
    def fake_fetcher(url: str, _timeout_seconds: int) -> str:
        from urllib.parse import urlparse, parse_qs

        qs = parse_qs(urlparse(url).query)
        offset = int(qs.get("offset", ["0"])[0])
        if offset == 0:
            return json.dumps(
                {
                    "dom": (
                        '<div class="r"><a href="https://www.toutiao.com/group/111/">A</a></div>'
                        '<div class="r"><a href="https://www.toutiao.com/group/222/">B</a></div>'
                    ),
                    "count": 2,
                }
            )
        if offset == 10:
            return json.dumps(
                {
                    "dom": (
                        '<div class="r"><a href="https://www.toutiao.com/group/111/">A dup</a></div>'
                        '<div class="r"><a href="https://www.toutiao.com/group/333/">C</a></div>'
                    ),
                    "count": 2,
                }
            )
        return json.dumps({"dom": "", "count": 0})

    items = fetch_toutiao_search_pages(
        "AI工具", fetched_at="2026-07-13T08:00:00+08:00",
        max_pages=3, per_page=10, fetcher=fake_fetcher,
    )
    titles = [item.title for item in items]
    assert titles.count("A") == 1
    assert "B" in titles
    assert "C" in titles
    assert len(items) == 3


def test_fetch_item_details_uses_content_html_when_live_fetch_fails():
    """Bug fix: when the desktop page is JS-rendered (urllib gets no <article>),
    the article body still comes back via the mobile article_info API and is
    stored in raw_payload['content_html']. Make sure it ends up in detail.content.
    """
    captured_urls: list[str] = []

    def empty_fetcher(url: str, timeout_seconds: int) -> str:
        captured_urls.append(url)
        # Simulate a JS-rendered SPA — no <article> tag in static HTML.
        return (
            "<html><head></head>"
            "<body><div class='container'><div id='app'></div></div></body>"
            "</html>"
        )

    content_html = (
        "<p>点击进入招聘合集</p>"
        "<p>更多国资央企精彩动态</p>"
        "<p>尽在国资小新视频号</p>"
        "<p>———— / END / ————</p>"
        "<p>责任编辑丨蔡豪</p>"
        "<script>var x = 1;</script>"
        "<style>.foo { color: red }</style>"
        "<mp-common-videosnap data-desc='国资小新 hello'></mp-common-videosnap>"
    )
    item = HotItem(
        item_id="toutiao_search_校招_1",
        platform="toutiao",
        item_type="search_result",
        title="【",
        url="/search/jump?aid=1455&jtoken=abc123",
        rank=1,
        heat=HeatMetrics(value=304, label="304", metric_name="article_heat"),
        summary="校招",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-14T17:01:25+08:00",
        fetch_status="success",
        raw_payload={
            "search_phrase": "校招",
            "source_kind": "article_info",
            "article_heat": 304,
            "content_html": content_html,
        },
    )

    details = fetch_toutiao_item_details([item], fetcher=empty_fetcher)
    assert len(details) == 1
    detail = details[0]

    assert detail.fetch_status == "partial"
    assert detail.extraction_method == "article_info_content_html"
    assert "招聘合集" in detail.content
    assert "责任编辑丨蔡豪" in detail.content
    assert detail.content != "校招"
    assert "<script>" not in detail.content
    assert "<style>" not in detail.content
    assert "<p>" not in detail.content
    assert "var x = 1" not in detail.content
    # URL field must keep the raw /search/jump URL so _write_article_text
    # can still match the detail back to its candidate.
    assert detail.url.startswith("/search/jump")
    # raw_payload pass-through for downstream consumers
    assert detail.raw_payload["content_source"] == "article_info"
    # Live fetch was tried (resolve before extract)
    assert any("/search/jump" in url or "toutiao.com" in url for url in captured_urls)
    # Block-level tags should preserve paragraph breaks so the saved article
    # file is readable instead of one long single-spaced line.
    assert "招聘合集" in detail.content
    paragraphs = [line for line in detail.content.splitlines() if line.strip()]
    assert len(paragraphs) >= 3, detail.content
    for expected in ("招聘合集", "国资央企", "视频号", "责任编辑"):
        assert any(expected in p for p in paragraphs), detail.content


def test_fetch_item_details_falls_back_to_summary_when_no_content_html():
    """When neither the live fetch nor content_html gives a body, we still
    return a partial detail — content must come from item.summary so report
    rendering doesn't crash."""
    def empty_fetcher(_url: str, _timeout_seconds: int) -> str:
        return "<html></html>"

    item = HotItem(
        item_id="toutiao_search_x",
        platform="toutiao",
        item_type="search_result",
        title="【",
        url="/search/jump?aid=1&jtoken=z",
        rank=1,
        heat=HeatMetrics(value=1, label="1", metric_name="article_heat"),
        summary="校招",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-14T00:00:00+08:00",
        fetch_status="success",
        raw_payload={"search_phrase": "校招", "source_kind": "article_info"},
    )

    details = fetch_toutiao_item_details([item], fetcher=empty_fetcher)
    assert len(details) == 1
    detail = details[0]
    assert detail.fetch_status == "partial"
    assert detail.extraction_method == "toutiao_hot_board_payload"
    assert detail.content == "校招"


def test_fetch_item_details_uses_article_title_when_available():
    """article_info API returns a real title even when the search result's
    title field is the search keyword. detail.title should pick that up
    via raw_payload['article_title']."""
    def empty_fetcher(_url: str, _timeout_seconds: int) -> str:
        return "<html></html>"

    item = HotItem(
        item_id="toutiao_search_t",
        platform="toutiao",
        item_type="search_result",
        title="【",
        url="/search/jump?aid=1&jtoken=z",
        rank=1,
        heat=HeatMetrics(value=1, label="1", metric_name="article_heat"),
        summary="校招",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-14T00:00:00+08:00",
        fetch_status="success",
        raw_payload={
            "search_phrase": "校招",
            "source_kind": "article_info",
            "article_title": "中央财经大学2027年校园招聘公告",
            "content_html": "<p>正文第一段。</p>",
        },
    )

    details = fetch_toutiao_item_details([item], fetcher=empty_fetcher)
    detail = details[0]
    assert detail.title == "中央财经大学2027年校园招聘公告"
    assert detail.extraction_method == "article_info_content_html"


def test_fetch_item_details_falls_back_to_item_title_when_article_title_missing():
    def empty_fetcher(_url: str, _timeout_seconds: int) -> str:
        return "<html></html>"

    item = HotItem(
        item_id="toutiao_search_fb",
        platform="toutiao",
        item_type="search_result",
        title="学校招聘信息",
        url="/search/jump?aid=1&jtoken=z",
        rank=1,
        heat=HeatMetrics(value=1, label="1", metric_name="article_heat"),
        summary="",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-14T00:00:00+08:00",
        fetch_status="success",
        raw_payload={"search_phrase": "校招", "source_kind": "article_info", "content_html": "<p>x</p>"},
    )

    details = fetch_toutiao_item_details([item], fetcher=empty_fetcher)
    detail = details[0]
    assert detail.title == "学校招聘信息"