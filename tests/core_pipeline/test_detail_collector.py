import unittest

from src.core_pipeline.detail_collector import collect_topic_details
from src.core_pipeline.types import HotRecord


def hot_record(record_id: str, platform: str, title: str) -> HotRecord:
    return HotRecord(
        id=record_id,
        source="dailyhotapi",
        platform=platform,
        route=platform,
        category="core_discovery",
        title=title,
        rank=1,
        hot_value="100",
        url="https://example.com/hot",
        mobile_url="",
        desc="热榜摘要不能替代详情",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-22T20:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )


class DetailCollectorTests(unittest.TestCase):
    def test_collect_topic_details_writes_non_empty_baidu_detail_from_search_results(self):
        topic = {
            "topic_key": "某事件",
            "canonical_title": "某事件",
            "hot_record_ids": ["hot_weibo_001"],
            "records": [hot_record("hot_weibo_001", "weibo", "某事件")],
        }

        def search_provider(query: str):
            if "怎么回事" in query:
                return [{"title": "某事件详情", "snippet": "这里是事件的详细经过", "url": "https://news.example.com/a"}]
            return []

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=search_provider,
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        )

        baidu_rows = [row for row in evidence if row.platform == "baidu"]
        self.assertEqual(baidu_rows[0].fetch_status, "ok")
        self.assertIn("这里是事件的详细经过", baidu_rows[0].content)

    def test_collect_topic_details_records_empty_content_when_search_has_no_detail(self):
        topic = {
            "topic_key": "某事件",
            "canonical_title": "某事件",
            "hot_record_ids": ["hot_weibo_001"],
            "records": [hot_record("hot_weibo_001", "weibo", "某事件")],
        }

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=lambda query: [],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        )

        self.assertTrue(any(row.fetch_status == "empty_content" for row in evidence if row.platform == "baidu"))
        self.assertTrue(any(row.fetch_status == "login_required" for row in evidence if row.platform == "weibo"))


if __name__ == "__main__":
    unittest.main()
