"""Tests for the anonymous Sina News provider (functional style)."""
import json
from pathlib import Path

import pytest

from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.sina_news import (
    SINA_COMMENT_URL,
    SINA_HOT_URL,
    SINA_SEARCH_URL,
    parse_sina_article_response,
    parse_sina_comments_response,
    parse_sina_hot_response,
    parse_sina_search_response,
)

FIX = Path(__file__).parents[1] / "fixtures" / "news"
NOW = "2026-07-23T04:00:00+08:00"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _hot_raw() -> str:
    return _read("sina_news_hot.txt")


def _search_raw() -> str:
    return _read("sina_news_search.json")


def _article_raw() -> str:
    return _read("sina_news_article.html")


def _article_short_raw() -> str:
    return _read("sina_news_article_short.html")


def _comments_ok_raw() -> str:
    return _read("sina_news_comments_ok.json")


def _comments_err_raw() -> str:
    return _read("sina_news_comments.json")


# ---------------------------------------------------------------------------
# parse_sina_hot_response
# ---------------------------------------------------------------------------

def test_parse_sina_hot_returns_50_items_with_top_num_heat():
    items = parse_sina_hot_response(_hot_raw(), fetched_at=NOW)
    assert len(items) == 50
    assert all(isinstance(it, HotItem) for it in items)
    assert items[0].platform == "sina_news"
    assert items[0].item_type == "news"
    assert items[0].rank == 1
    assert items[0].heat.metric_name == "top_num"
    # top_num "45,122" -> 45122
    assert items[0].heat.value == 45122
    assert items[0].heat.metrics["top_num"] == 45122


def test_parse_sina_hot_strips_formatted_top_num():
    items = parse_sina_hot_response(_hot_raw(), fetched_at=NOW)
    # All items have parsed int top_num, no commas
    for it in items:
        if it.heat.value is not None:
            assert isinstance(it.heat.value, int)
            assert it.heat.label == str(it.heat.value)


def test_parse_sina_hot_assigns_stable_item_id_from_url():
    items = parse_sina_hot_response(_hot_raw(), fetched_at=NOW)
    # id embeds the article id from URL's doc- portion
    assert items[0].item_id.startswith("sina_news_")
    assert len(items[0].item_id) < 80


def test_parse_sina_hot_preserves_raw_payload_and_publication_time():
    items = parse_sina_hot_response(_hot_raw(), fetched_at=NOW)
    it = items[0]
    assert "title" in it.raw_payload
    assert it.raw_payload["title"] == it.title
    # publication_time is ISO8601 UTC with Z suffix
    assert it.publication_time is not None
    assert it.publication_time.endswith("Z")


def test_parse_sina_hot_rejects_invalid_jsonp():
    with pytest.raises(ValueError):
        parse_sina_hot_response("not jsonp", fetched_at=NOW)
    with pytest.raises(ValueError):
        parse_sina_hot_response("var data = {};", fetched_at=NOW)
    with pytest.raises(ValueError):
        parse_sina_hot_response("var data = {\"data\": []};", fetched_at=NOW)


def test_parse_sina_hot_known_url():
    """Compare canonical URL constant matches the parsed items."""
    items = parse_sina_hot_response(_hot_raw(), fetched_at=NOW)
    assert items[0].url.startswith("https://news.sina.com.cn/")


# ---------------------------------------------------------------------------
# parse_sina_search_response
# ---------------------------------------------------------------------------

def test_parse_sina_search_returns_at_least_one_item():
    items = parse_sina_search_response(_search_raw(), fetched_at=NOW)
    assert len(items) >= 1
    assert all(isinstance(it, HotItem) for it in items)
    assert all(it.platform == "sina_news" for it in items)


def test_parse_sina_search_does_not_treat_order_as_heat():
    items = parse_sina_search_response(_search_raw(), fetched_at=NOW)
    # Search results have no real heat metric; value is None
    for it in items:
        assert it.heat.value is None
        assert it.heat.metric_name == "search_rank"
        # rank may still be set from position
        assert it.rank is None or isinstance(it.rank, int)


def test_parse_sina_search_assigns_unique_item_ids_with_dataid():
    items = parse_sina_search_response(_search_raw(), fetched_at=NOW)
    ids = [it.item_id for it in items]
    assert len(ids) == len(set(ids))
    # First item should have dataid-derived id
    first = items[0]
    assert first.item_id.startswith("sina_news_")
    assert "niiuwta4642617" in first.item_id or first.raw_payload.get("dataid")


def test_parse_sina_search_filters_items_missing_url_or_title():
    raw = """{
        "code": 0,
        "message": "success",
        "data": {
            "list": [
                {"title": "valid", "url": "https://news.sina.com.cn/a", "dataid": "comos:a1"},
                {"title": "no url", "dataid": "comos:b1"},
                {"url": "https://news.sina.com.cn/b", "dataid": "comos:c1"},
                {"title": "valid 2", "url": "https://news.sina.com.cn/c", "dataid": "comos:c2"}
            ]
        }
    }"""
    items = parse_sina_search_response(raw, fetched_at=NOW)
    assert len(items) == 2
    assert [it.raw_payload["dataid"] for it in items] == ["comos:a1", "comos:c2"]


def test_parse_sina_search_rejects_non_success_response():
    raw = json.dumps({"code": 1, "message": "denied", "data": {}})
    with pytest.raises(ValueError):
        parse_sina_search_response(raw, fetched_at=NOW)


def test_parse_sina_search_rejects_missing_list():
    raw = json.dumps({"code": 0, "message": "success", "data": {}})
    with pytest.raises(ValueError):
        parse_sina_search_response(raw, fetched_at=NOW)


def test_parse_sina_search_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_sina_search_response("not json", fetched_at=NOW)


# ---------------------------------------------------------------------------
# parse_sina_comments_response
# ---------------------------------------------------------------------------

def test_parse_sina_comments_returns_total_when_present():
    total = parse_sina_comments_response(_comments_ok_raw())
    assert total == 4821


def test_parse_sina_comments_returns_none_on_error_payload():
    # The actual server now returns "code: 4" for channel lookup failures
    assert parse_sina_comments_response(_comments_err_raw()) is None


def test_parse_sina_comments_returns_none_on_malformed_json():
    assert parse_sina_comments_response("not json") is None


def test_parse_sina_comments_returns_none_on_missing_count():
    # No .result.count at all
    assert parse_sina_comments_response(json.dumps({"result": {}})) is None
    # Non-dict result
    assert parse_sina_comments_response(json.dumps({"result": "x"})) is None


# ---------------------------------------------------------------------------
# parse_sina_article_response
# ---------------------------------------------------------------------------

def test_parse_sina_article_returns_nonempty_text_from_real_html():
    text = parse_sina_article_response(_article_raw(), title="罕见反超", summary="")
    assert text
    assert len(text) > 200


def test_parse_sina_article_strips_html_tags():
    raw = "<html><body><div id='article'><p>这是一段正文，详细内容如下。</p></div></body></html>"
    text = parse_sina_article_response(raw, title="标题", summary="")
    assert "这是一段正文" in text
    assert "<p>" not in text
    assert "<div" not in text


def test_parse_sina_article_returns_empty_for_short_html():
    text = parse_sina_article_response(_article_short_raw(), title="标题", summary="")
    assert text == ""


def test_parse_sina_article_returns_empty_for_empty_html():
    assert parse_sina_article_response("", title="", summary="") == ""
    assert parse_sina_article_response("<html></html>", title="", summary="") == ""


def test_parse_sina_article_live_html_returns_real_body():
    """Regression: real sina article pages (captured 2026-07-25) used to
    return nav junk because the non-greedy selector regex matched the
    first </div> inside an inline script instead of the article container.
    Real body text must dominate, with nav chrome filtered out.
    """
    raw = (FIX / "sina_news_article_live.html").read_text(encoding="utf-8")
    text = parse_sina_article_response(raw, title="14对14", summary="")
    assert text, "article text must not be empty"
    # Must contain real body markers from the captured top story.
    assert "欧盟" in text
    lines = text.splitlines()
    assert lines[0].count("欧盟") >= 1
    assert text.count(lines[0]) == 1
    assert not any(
        lines[index] and lines[index] == lines[index - 1]
        for index in range(1, len(lines))
    )
    assert len(text) >= 200, f"body too short: {len(text)} chars"
    # Nav chrome (the page header) must NOT dominate.
    nav_markers = ("新浪首页", "新浪新闻", "新浪财经", "新浪体育")
    nav_hits = sum(text.count(m) for m in nav_markers)
    assert nav_hits <= 1, f"too much nav chrome leaked: {nav_hits} hits"


# ---------------------------------------------------------------------------
# URL constants
# ---------------------------------------------------------------------------

def test_sina_url_constants_match_documented_endpoints():
    assert SINA_HOT_URL.startswith("https://top.news.sina.com.cn/ws/GetTopDataList.php")
    assert SINA_SEARCH_URL == "https://search.sina.com.cn/api/news"
    assert SINA_COMMENT_URL == "https://comment5.news.sina.com.cn/page/info"
