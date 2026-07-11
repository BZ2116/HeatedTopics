import json

from heated_topics_v3.contracts import TopicQuery
from heated_topics_v3.providers.toutiao import (
    TOUTIAO_HOT_BOARD_URL,
    TOUTIAO_SEARCH_URL,
    build_toutiao_search_phrases,
    fetch_toutiao_hot_items,
    fetch_toutiao_item_detail,
    fetch_toutiao_search_items,
    merge_toutiao_items,
    parse_toutiao_hot_board_response,
    parse_toutiao_search_response,
)


def test_parse_toutiao_hot_board_response_maps_hot_items():
    payload = {
        "status": "success",
        "data": [
            {
                "ClusterId": 7661093259842322486,
                "Title": "AI Agent product launches",
                "Url": "https://www.toutiao.com/trending/7661093259842322486/",
                "HotValue": "59252919",
                "QueryWord": "AI Agent product launches",
                "InterestCategory": ["technology"],
                "Label": "hot",
            }
        ],
    }

    items = parse_toutiao_hot_board_response(
        json.dumps(payload),
        fetched_at="2026-07-11T14:50:00+08:00",
        matched_query_ids=("tech_ai_creator_q_001_core_hot",),
    )

    assert len(items) == 1
    item = items[0]
    assert item.item_id == "toutiao_7661093259842322486"
    assert item.platform == "toutiao"
    assert item.item_type == "topic"
    assert item.title == "AI Agent product launches"
    assert item.url == "https://www.toutiao.com/trending/7661093259842322486/"
    assert item.rank == 1
    assert item.heat.value == 59252919
    assert item.heat.label == "59252919"
    assert item.heat.metric_name == "hot_value"
    assert item.heat.metrics == {"hot_value": 59252919}
    assert item.summary == "AI Agent product launches"
    assert item.category == "technology"
    assert item.matched_query_ids == ("tech_ai_creator_q_001_core_hot",)
    assert item.fetch_status == "success"
    assert item.raw_payload["Label"] == "hot"


def test_fetch_toutiao_hot_items_uses_hot_board_url_and_injected_fetcher():
    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        assert url == TOUTIAO_HOT_BOARD_URL
        assert timeout_seconds == 20
        return json.dumps({"status": "success", "data": []})

    items = fetch_toutiao_hot_items(
        fetched_at="2026-07-11T14:50:00+08:00",
        fetcher=fake_fetcher,
    )

    assert items == []


def test_build_toutiao_search_phrases_expands_profile_queries():
    queries = (
        TopicQuery(
            query_id="tech_ai_creator_q_001_core_hot",
            profile_id="tech_ai_creator",
            query="AI Agent MCP",
            intent="profile_core_hot",
            target_platforms=("toutiao",),
            keywords=("AI Agent", "MCP"),
            usage="filter_and_enrich_hot_lists",
            priority=100,
        ),
        TopicQuery(
            query_id="tech_ai_creator_q_002_entity_hot",
            profile_id="tech_ai_creator",
            query="Claude Code",
            intent="profile_entity_hot",
            target_platforms=("toutiao",),
            keywords=("Claude Code",),
            usage="filter_and_enrich_hot_lists",
            priority=80,
        ),
    )

    phrases = build_toutiao_search_phrases(queries)

    assert phrases == (
        "AI Agent MCP",
        "AI Agent",
        "AI智能体",
        "智能体",
        "人工智能",
        "大模型",
        "MCP",
        "MCP 协议",
        "Claude Code",
        "Claude Code AI编程",
        "AI编程",
        "编程助手",
        "代码生成",
    )


def test_parse_toutiao_search_response_maps_dom_results_to_hot_items():
    payload = {
        "keyword": "AI智能体",
        "count": 2,
        "dom": """
        <div class="result-card">
          <a href="https://www.toutiao.com/article/1">AI智能体创业公司融资</a>
          <div>阅读 12万 评论 345</div>
          <p>AI智能体正在进入企业工作流。</p>
        </div>
        <div class="result-card">
          <a href="https://www.toutiao.com/article/2">AI智能体产品盘点</a>
          <div>热度 8866</div>
          <p>多款AI产品更新。</p>
        </div>
        """,
    }

    items = parse_toutiao_search_response(
        json.dumps(payload),
        phrase="AI智能体",
        fetched_at="2026-07-11T15:20:00+08:00",
    )

    assert [item.item_id for item in items] == ["toutiao_search_1", "toutiao_search_2"]
    assert items[0].title == "AI智能体创业公司融资"
    assert items[0].url == "https://www.toutiao.com/article/1"
    assert items[0].item_type == "search_result"
    assert items[0].heat.metric_name == "search_engagement"
    assert items[0].heat.metrics["reads"] == 120000
    assert items[0].heat.metrics["comments"] == 345
    assert items[0].summary == "AI智能体正在进入企业工作流。"
    assert items[0].raw_payload["search_phrase"] == "AI智能体"
    assert items[0].raw_payload["alias_for"] == "AI Agent"
    assert items[0].raw_payload["source_kind"] == "search_result"
    assert items[1].heat.value == 8866
    assert items[1].heat.metric_name == "search_heat"


def test_fetch_toutiao_search_items_calls_search_endpoint_for_each_phrase():
    calls = []

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        calls.append(url)
        return json.dumps({"keyword": "AI智能体", "count": 0, "dom": ""})

    items = fetch_toutiao_search_items(
        phrases=("AI智能体", "MCP 协议"),
        fetched_at="2026-07-11T15:20:00+08:00",
        fetcher=fake_fetcher,
    )

    assert items == []
    assert calls[0].startswith(f"{TOUTIAO_SEARCH_URL}?")
    assert "keyword=AI" in calls[0]
    assert "keyword=MCP" in calls[1]


def test_parse_toutiao_search_response_keeps_keyword_hit_when_dom_has_no_result_links():
    items = parse_toutiao_search_response(
        json.dumps({"keyword": "AI智能体", "count": 1, "dom": "<div>相关搜索卡片</div>"}),
        phrase="AI智能体",
        fetched_at="2026-07-11T15:20:00+08:00",
    )

    assert len(items) == 1
    assert items[0].title == "AI智能体"
    assert items[0].item_type == "search_result"
    assert items[0].heat.metric_name == "search_rank"
    assert items[0].raw_payload["source_kind"] == "search_keyword_hit"
    assert items[0].raw_payload["alias_for"] == "AI Agent"


def test_parse_toutiao_search_response_skips_profile_links():
    items = parse_toutiao_search_response(
        json.dumps(
            {
                "keyword": "编程助手",
                "count": 1,
                "dom": """
                <a href="https://profile.zjurl.cn/rogue/ugc/profile/?user_id=1">作者主页</a>
                <a href="/search/jump?aid=1455">编程助手案例</a>
                """,
            }
        ),
        phrase="编程助手",
        fetched_at="2026-07-11T15:20:00+08:00",
    )

    assert len(items) == 1
    assert items[0].title == "编程助手案例"


def test_merge_toutiao_items_uses_hot_board_heat_for_overlapping_urls():
    search_items = parse_toutiao_search_response(
        json.dumps(
            {
                "keyword": "AI智能体",
                "count": 1,
                "dom": '<a href="https://www.toutiao.com/article/1">AI智能体创业公司融资</a>',
            }
        ),
        phrase="AI智能体",
        fetched_at="2026-07-11T15:20:00+08:00",
    )
    hot_board_items = parse_toutiao_hot_board_response(
        json.dumps(
            {
                "data": [
                    {
                        "ClusterId": "1",
                        "Title": "AI智能体创业公司融资",
                        "Url": "https://www.toutiao.com/article/1",
                        "HotValue": "9000",
                        "QueryWord": "AI智能体创业公司融资",
                    }
                ]
            }
        ),
        fetched_at="2026-07-11T15:20:00+08:00",
    )

    merged = merge_toutiao_items(search_items, hot_board_items)

    assert len(merged) == 1
    assert merged[0].heat.value == 9000
    assert merged[0].heat.metric_name == "hot_value"
    assert merged[0].raw_payload["source_kind"] == "search_hot_board_overlap"


def test_merge_toutiao_items_keeps_distinct_keyword_hits():
    first = parse_toutiao_search_response(
        json.dumps({"keyword": "人工智能", "count": 1, "dom": "<div>相关搜索卡片</div>"}),
        phrase="人工智能",
        fetched_at="2026-07-11T15:20:00+08:00",
    )[0]
    second = parse_toutiao_search_response(
        json.dumps({"keyword": "知识库问答", "count": 1, "dom": "<div>相关搜索卡片</div>"}),
        phrase="知识库问答",
        fetched_at="2026-07-11T15:20:00+08:00",
    )[0]

    merged = merge_toutiao_items([first, second], [])

    assert [item.title for item in merged] == ["人工智能", "知识库问答"]


def test_fetch_toutiao_item_detail_extracts_html_article_text():
    items = parse_toutiao_hot_board_response(
        json.dumps(
            {
                "data": [
                    {
                        "ClusterId": "1",
                        "Title": "AI Agent product launches",
                        "Url": "https://www.toutiao.com/article/1",
                        "HotValue": "100",
                        "QueryWord": "AI Agent",
                    }
                ]
            }
        ),
        fetched_at="2026-07-11T14:50:00+08:00",
    )
    calls = []

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        calls.append((url, timeout_seconds))
        return """
        <html>
          <body>
            <article>
              <style>.article{color:red}</style>
              <h1>AI Agent product launches</h1>
              <p>Detailed Toutiao article body.</p>
              <script>window.DATA = {}</script>
            </article>
          </body>
        </html>
        """

    detail = fetch_toutiao_item_detail(items[0], fetcher=fake_fetcher)

    assert calls == [("https://www.toutiao.com/article/1", 20)]
    assert detail.item_id == "toutiao_1"
    assert detail.platform == "toutiao"
    assert detail.title == "AI Agent product launches"
    assert detail.content == "AI Agent product launches\nDetailed Toutiao article body."
    assert detail.extraction_method == "toutiao_article_page"
    assert detail.fetch_status == "success"


def test_fetch_toutiao_item_detail_falls_back_to_hot_item_summary():
    items = parse_toutiao_hot_board_response(
        json.dumps(
            {
                "data": [
                    {
                        "ClusterId": "1",
                        "Title": "AI Agent product launches",
                        "Url": "https://webcast-open.douyin.com/open/media_live/1",
                        "HotValue": "100",
                        "QueryWord": "AI Agent",
                    }
                ]
            }
        ),
        fetched_at="2026-07-11T14:50:00+08:00",
    )

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        return "<html><body>No article tag.</body></html>"

    detail = fetch_toutiao_item_detail(items[0], fetcher=fake_fetcher)

    assert detail.content == "AI Agent"
    assert detail.extraction_method == "toutiao_hot_board_payload"
    assert detail.fetch_status == "partial"


def test_fetch_toutiao_item_detail_normalizes_relative_search_url():
    items = parse_toutiao_search_response(
        json.dumps(
            {
                "keyword": "编程助手",
                "count": 1,
                "dom": '<a href="/search/jump?aid=1455">编程助手案例</a>',
            }
        ),
        phrase="编程助手",
        fetched_at="2026-07-11T15:20:00+08:00",
    )
    calls = []

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        calls.append(url)
        return "<html><body>No article tag.</body></html>"

    detail = fetch_toutiao_item_detail(items[0], fetcher=fake_fetcher)

    assert calls == ["https://so.toutiao.com/search/jump?aid=1455"]
    assert detail.content == items[0].summary
    assert detail.fetch_status == "partial"
