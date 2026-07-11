import json

from heated_topics_v3.providers.toutiao import (
    TOUTIAO_HOT_BOARD_URL,
    fetch_toutiao_hot_items,
    fetch_toutiao_item_detail,
    parse_toutiao_hot_board_response,
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
