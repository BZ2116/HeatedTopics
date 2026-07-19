from heated_topics_v3.providers.baidu import (
    parse_baidu_board_response,
    parse_baidu_search_response,
)


BOARD_FIXTURE = """{
  "success": true,
  "data": {"cards": [{"component": "tabTextList", "title": "热搜榜", "content": [
    {"content": [
      {"isTop": true, "url": "https://m.baidu.com/s?word=%E6%90%BA%E6%89%8B&sa=fyb_news", "word": "携手"},
      {"isTop": false, "index": 1, "url": "https://m.baidu.com/s?word=%E6%B3%95&sa=fyb_news", "word": "法国", "hotTag": "3"},
      {"isTop": false, "index": 2, "url": "https://m.baidu.com/s?word=%E4%BD%BF%E9%A6%86&sa=fyb_news", "word": "使馆"}
    ]}
  ]}]}
}"""


def test_parse_board_returns_hotword_hot_items():
    items = parse_baidu_board_response(
        BOARD_FIXTURE,
        fetched_at="2026-07-19T20:00:00+08:00",
        matched_query_ids=("tech_ai_creator_q_001_core_hot",),
    )
    assert [i.item_id for i in items] == [
        "baidu_word_携手",
        "baidu_word_法国",
        "baidu_word_使馆",
    ]
    assert all(it.platform == "baidu" for it in items)
    assert all(it.item_type == "hotword" for it in items)
    assert items[0].rank is None  # isTop row
    assert items[1].rank == 1
    assert items[1].heat.metric_name == "hot_tag"
    assert items[1].heat.value == 3
    assert items[1].matched_query_ids == ("tech_ai_creator_q_001_core_hot",)


SEARCH_FIXTURE = """
<html><body>
<a href="https://baijiahao.baidu.com/s?id=1110000000000000001">携手推动人工智能</a>
<a href="https://baijiahao.baidu.com/s?id=2220000000000000002">百度热搜抓取工具</a>
<a href="https://example.com/something-else">unrelated</a>
<a href="https://baijiahao.baidu.com/s?id=1110000000000000001">dup</a>
</body></html>
"""


def test_parse_search_extracts_unique_baijiahao_links():
    articles = parse_baidu_search_response(SEARCH_FIXTURE, source_word="携手")
    assert [a.article_id for a in articles] == [
        "1110000000000000001",
        "2220000000000000002",
    ]
    assert articles[0].title == "携手推动人工智能"
    assert articles[1].title == "百度热搜抓取工具"
    assert all(a.platform == "baidu" for a in articles)
    assert all(a.source_word == "携手" for a in articles)


def test_parse_search_returns_empty_on_no_baijiahao():
    articles = parse_baidu_search_response(
        "<html><body>no article links here</body></html>",
        source_word="unused",
    )
    assert articles == []


def test_parse_search_prefers_h3_text_inside_anchor():
    html = """<html><body>
<a href="https://baijiahao.baidu.com/s?id=3330000000000000003"><h3>头条新闻标题</h3><span>junk</span></a>
</body></html>"""
    articles = parse_baidu_search_response(html, source_word="头条")
    assert [a.article_id for a in articles] == ["3330000000000000003"]
    assert articles[0].title == "头条新闻标题"
