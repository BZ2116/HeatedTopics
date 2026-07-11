import json

from heated_topics_v3.providers.juejin import JUEJIN_HOT_RANK_URL, fetch_juejin_hot_items, parse_juejin_rank_response


def test_parse_juejin_rank_response_maps_ranked_articles_to_hot_items():
    payload = {
        "err_no": 0,
        "err_msg": "success",
        "data": [
            {
                "content": {
                    "content_id": "7659763781161730102",
                    "title": "Fiber node and React runtime",
                    "brief": "A deep dive into React Fiber.",
                    "category_id": "6809637767543259144",
                    "tag_ids": ["6809640407484334093"],
                },
                "content_counter": {
                    "view": 12525,
                    "like": 18,
                    "collect": 36,
                    "hot_rank": 5886,
                    "comment_count": 10,
                    "interact_count": 28,
                },
                "author": {
                    "user_id": "1433418891015310",
                    "name": "Author Name",
                },
            }
        ],
    }

    items = parse_juejin_rank_response(
        json.dumps(payload),
        fetched_at="2026-07-11T13:28:53+08:00",
        matched_query_ids=("tech_ai_creator_q_001_core_hot",),
    )

    assert len(items) == 1
    item = items[0]
    assert item.item_id == "juejin_7659763781161730102"
    assert item.platform == "juejin"
    assert item.item_type == "article"
    assert item.title == "Fiber node and React runtime"
    assert item.url == "https://juejin.cn/post/7659763781161730102"
    assert item.rank == 1
    assert item.heat.value == 5886
    assert item.heat.metric_name == "hot_rank"
    assert item.heat.metrics == {
        "views": 12525,
        "likes": 18,
        "collects": 36,
        "comments": 10,
        "interactions": 28,
    }
    assert item.summary == "A deep dive into React Fiber."
    assert item.category == "6809637767543259144"
    assert item.matched_query_ids == ("tech_ai_creator_q_001_core_hot",)
    assert item.fetch_status == "success"
    assert item.raw_payload["author"]["name"] == "Author Name"


def test_fetch_juejin_hot_items_uses_rank_url_and_injected_fetcher():
    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        assert url == JUEJIN_HOT_RANK_URL
        assert timeout_seconds == 20
        return json.dumps({"err_no": 0, "data": []})

    items = fetch_juejin_hot_items(
        fetched_at="2026-07-11T13:28:53+08:00",
        fetcher=fake_fetcher,
    )

    assert items == []
