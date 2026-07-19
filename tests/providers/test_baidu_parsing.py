from heated_topics_v3.providers.baidu import parse_baidu_board_response


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