import unittest

from src.core_pipeline.recent_topics import (
    collection_window_days,
    deduplicate_hot_records,
    normalize_topic_key,
)
from src.core_pipeline.types import HotRecord


def hot_record(record_id: str, platform: str, title: str, rank: int = 1) -> HotRecord:
    return HotRecord(
        id=record_id,
        source="dailyhotapi",
        platform=platform,
        route=platform,
        category="core_discovery",
        title=title,
        rank=rank,
        hot_value="100",
        url=f"https://example.com/{record_id}",
        mobile_url="",
        desc="",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-22T20:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )


class RecentTopicsTests(unittest.TestCase):
    def test_collection_window_days_accepts_supported_windows(self):
        self.assertEqual(collection_window_days("today"), 1)
        self.assertEqual(collection_window_days("last_7_days"), 7)

    def test_collection_window_days_rejects_unknown_window(self):
        with self.assertRaises(ValueError):
            collection_window_days("month")

    def test_normalize_topic_key_removes_hot_list_noise(self):
        self.assertEqual(normalize_topic_key("  某事件 爆！ "), "某事件")
        self.assertEqual(normalize_topic_key("某事件 热"), "某事件")

    def test_deduplicate_hot_records_keeps_all_source_ids(self):
        records = [
            hot_record("hot_weibo_001", "weibo", "某事件 爆", rank=1),
            hot_record("hot_baidu_003", "baidu", "某事件", rank=3),
            hot_record("hot_zhihu_001", "zhihu", "另一个话题", rank=2),
        ]

        topics = deduplicate_hot_records(records)

        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["topic_key"], "某事件")
        self.assertEqual(topics[0]["hot_record_ids"], ["hot_weibo_001", "hot_baidu_003"])
        self.assertEqual(topics[0]["platforms"], ["baidu", "weibo"])


if __name__ == "__main__":
    unittest.main()