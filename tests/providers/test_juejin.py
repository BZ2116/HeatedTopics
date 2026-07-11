from heated_topics_v3.contracts import TopicQuery
from heated_topics_v3.matching import match_hot_item_to_queries
from heated_topics_v3.providers.juejin import (
    JUEJIN_ARTICLE_DETAIL_URL,
    JUEJIN_HOT_RANK_URL,
    fetch_juejin_hot_items,
    fetch_juejin_item_detail,
    parse_juejin_rank_response,
)

import json


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


def test_fetch_juejin_item_detail_prefers_detail_api():
    items = parse_juejin_rank_response(
        json.dumps(
            {
                "err_no": 0,
                "data": [
                    {
                        "content": {
                            "content_id": "1",
                            "title": "Test",
                            "brief": "Brief.",
                            "category_id": "tech",
                        },
                        "content_counter": {"hot_rank": 100},
                    }
                ],
            }
        ),
        fetched_at="2026-07-11T13:28:53+08:00",
    )
    calls = []

    def fake_fetcher(url: str, timeout_seconds: int, body: dict[str, str] | None = None) -> str:
        calls.append((url, timeout_seconds, body))
        return json.dumps(
            {
                "err_no": 0,
                "data": {
                    "article_info": {
                        "title": "Test",
                        "brief_content": "Brief.",
                        "mark_content": "## Detailed markdown\n\nFull article body.",
                        "ctime": "1783760400",
                    },
                    "author_user_info": {"user_name": "Author"},
                    "tags": [{"tag_name": "AI"}],
                },
            }
        )

    detail = fetch_juejin_item_detail(items[0], fetcher=fake_fetcher)

    assert calls == [(JUEJIN_ARTICLE_DETAIL_URL, 20, {"article_id": "1"})]
    assert detail.item_id == "juejin_1"
    assert detail.title == "Test"
    assert detail.author == "Author"
    assert detail.tags == ("AI",)
    assert detail.content == "## Detailed markdown\n\nFull article body."
    assert detail.extraction_method == "juejin_detail_api"
    assert detail.fetch_status == "success"


def test_fetch_juejin_item_detail_falls_back_to_article_page():
    items = parse_juejin_rank_response(
        json.dumps(
            {
                "err_no": 0,
                "data": [
                    {
                        "content": {
                            "content_id": "1",
                            "title": "Test",
                            "brief": "Brief.",
                            "category_id": "tech",
                        },
                        "content_counter": {"hot_rank": 100},
                    }
                ],
            }
        ),
        fetched_at="2026-07-11T13:28:53+08:00",
    )
    calls = []

    def fake_fetcher(url: str, timeout_seconds: int, body: dict[str, str] | None = None) -> str:
        calls.append((url, body))
        if body is not None:
            return json.dumps({"err_no": 2, "err_msg": "参数错误", "data": None})
        return """
        <html>
          <body>
            <article>
              <style>.markdown-body{color:red}</style>
              <h1>Test</h1>
              <p>Fallback article content.</p>
              <script>window.__NUXT__ = {}</script>
            </article>
          </body>
        </html>
        """

    detail = fetch_juejin_item_detail(items[0], fetcher=fake_fetcher)

    assert calls == [
        (JUEJIN_ARTICLE_DETAIL_URL, {"article_id": "1"}),
        ("https://juejin.cn/post/1", None),
    ]
    assert detail.content == "Test\nFallback article content."
    assert detail.extraction_method == "juejin_article_page"
    assert detail.fetch_status == "success"


def test_juejin_hot_item_can_be_matched_with_profile_query():
    items = parse_juejin_rank_response(
        json.dumps(
            {
                "err_no": 0,
                "data": [
                    {
                        "content": {
                            "content_id": "1",
                            "title": "AI Agent workflow with MCP",
                            "brief": "",
                            "category_id": "tech",
                        },
                        "content_counter": {"hot_rank": 100},
                    }
                ],
            }
        ),
        fetched_at="2026-07-11T13:28:53+08:00",
    )
    query = TopicQuery(
        query_id="tech_ai_creator_q_001_core_hot",
        profile_id="tech_ai_creator",
        query="AI Agent MCP",
        intent="profile_core_hot",
        target_platforms=("juejin",),
        keywords=("AI Agent", "MCP"),
        usage="filter_and_enrich_hot_lists",
        priority=100,
    )

    result = match_hot_item_to_queries(items[0], (query,))

    assert result.item.matched_query_ids == ("tech_ai_creator_q_001_core_hot",)
    assert result.match_terms == ("AI Agent", "MCP")
