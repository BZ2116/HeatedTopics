"""Bilibili search + article body parser tests."""
from __future__ import annotations

from heated_topics_v3.providers.bilibili import (
    BILIBILI_SEARCH_URL,
    build_search_url,
    parse_bilibili_search_response,
    parse_bilibili_article_response,
)


def test_build_search_url_signs_and_encodes():
    url = build_search_url("AI Agent", page=1, img_key="a" * 32, sub_key="b" * 32, wts=100)
    assert url.startswith(BILIBILI_SEARCH_URL)
    assert "search_type=article" in url
    assert "w_rid=" in url and "wts=100" in url


def test_parse_search_strips_em_and_reads_stats():
    resp = """{"code":0,"data":{"result":[
      {"id":123,"title":"AI <em class=\\"keyword\\">Agent</em> 指南","desc":"d",
       "view":1000,"like":50,"reply":8,"pub_time":1700000000,"mid":9,"author":"作者A"}
    ]}}"""
    items = parse_bilibili_search_response(resp, source_word="AI", fetched_at="2026-07-22T20:00:00+08:00")
    assert len(items) == 1
    it = items[0]
    assert it.title == "AI Agent 指南"
    assert it.raw_payload["cvid"] == "123"
    assert it.raw_payload["source_path"] == "B"
    assert it.heat.metrics["views"] == 1000
    assert it.heat.metrics["likes"] == 50


def test_parse_search_ignores_bad_rows():
    resp = '{"code":0,"data":{"result":[{"title":"无 id"}]}}'
    assert parse_bilibili_search_response(resp, source_word="x", fetched_at="t") == []


def test_parse_article_reads_body_and_stats_from_initial_state():
    html = (
        '<html><head><script>window.__INITIAL_STATE__='
        '{"readInfo":{"title":"AI Agent 指南","author":{"name":"作者A"},'
        '"stats":{"view":1000,"like":50,"coin":5,"favorite":20,"reply":8},'
        '"content":"<p>第一段正文。</p><p>第二段正文。</p>"}}'
        ';</script></head><body></body></html>'
    )
    detail = parse_bilibili_article_response(html, item_id="bilibili_article_123",
                                             item_url="https://www.bilibili.com/read/cv123",
                                             fetched_at="2026-07-22T20:00:00+08:00")
    assert detail.fetch_status == "success"
    assert detail.extraction_method == "bilibili_article_view"
    assert detail.content == "第一段正文。 第二段正文。"
    assert "<p>" not in detail.content
    assert detail.author == "作者A"


def test_parse_article_handles_inner_script_terminator_in_string():
    """Regression: a JSON string value containing `};` must not truncate the
    captured payload.

    The OLD regex `(\\{{.*?\\}});` would terminate at the first inner `};`
    inside a string value, corrupting the captured JSON. The new anchor
    `};</script>` requires the literal script close tag, so this case is
    captured correctly.
    """
    html = (
        '<html><head><script>window.__INITIAL_STATE__='
        '{"readInfo":{"title":"分号边界","author":{"name":"作者B"},'
        '"content":"<p>这里有 }; 这种分号子串。</p>"}}'
        ';</script></head><body></body></html>'
    )
    detail = parse_bilibili_article_response(html, item_id="bilibili_article_999",
                                             item_url="https://www.bilibili.com/read/cv999",
                                             fetched_at="2026-07-22T20:00:00+08:00")
    assert detail.fetch_status == "success"
    assert detail.content == "这里有 }; 这种分号子串。"


def test_parse_article_decodes_html_entities():
    html = (
        '<html><head><script>window.__INITIAL_STATE__='
        '{"readInfo":{"title":"实体测试","author":{"name":"作者C"},'
        '"content":"<p>foo &amp; bar &lt;ok&gt; &quot;q&quot;</p>"}}'
        ';</script></head><body></body></html>'
    )
    detail = parse_bilibili_article_response(html, item_id="bilibili_article_555",
                                             item_url="https://www.bilibili.com/read/cv555",
                                             fetched_at="2026-07-22T20:00:00+08:00")
    assert detail.fetch_status == "success"
    assert detail.content == 'foo & bar <ok> "q"'


def test_parse_article_empty_when_no_state():
    detail = parse_bilibili_article_response("<html></html>", item_id="x",
                                             item_url="u", fetched_at="t")
    assert detail.fetch_status == "empty"
    assert detail.content == ""