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

    def test_collect_topic_details_uses_source_url_when_search_has_no_detail(self):
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
            page_fetcher=lambda url: "<html><body><h1>某事件详情</h1><p>这里是原始页面里的详细内容。</p></body></html>",
        )

        source_rows = [row for row in evidence if row.source_method == "source_url"]
        self.assertEqual(source_rows[0].fetch_status, "ok")
        self.assertEqual(source_rows[0].topic_key, "某事件")
        self.assertIn("这里是原始页面里的详细内容", source_rows[0].content)

    def test_collect_topic_details_uses_normalized_topic_key_for_all_evidence(self):
        topic = {
            "topic_key": "testhottopic",
            "canonical_title": "test hot topic",
            "hot_record_ids": ["hot_weibo_001"],
            "records": [hot_record("hot_weibo_001", "weibo", "test hot topic")],
        }

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=lambda query: [],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
            page_fetcher=lambda url: "Detailed content from source page.",
        )

        self.assertEqual({row.topic_key for row in evidence}, {"testhottopic"})


if __name__ == "__main__":
    unittest.main()
