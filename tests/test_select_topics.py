import unittest

from src.hot_topic_types import HotRecord
from src.select_topics import normalize_title_key, select_topics


def record(platform, rank, title, hot="100", url="https://example.com"):
    return HotRecord(
        platform=platform,
        rank=rank,
        title=title,
        hot=hot,
        url=url,
        crawl_time="2026-06-12 08:30:00",
    )


class SelectTopicsTests(unittest.TestCase):
    def test_normalize_title_key_removes_spaces_and_lowercases_ascii(self):
        self.assertEqual(normalize_title_key("  AI 新产品 发布  "), "ai新产品发布")

    def test_select_topics_prioritizes_cross_platform_items(self):
        records = [
            record("weibo", 1, "AI 新产品发布"),
            record("baidu", 3, "AI新产品发布"),
            record("zhihu", 1, "另一个话题"),
            record("36kr", 2, "商业融资事件"),
            record("ithome", 1, "手机新品"),
        ]

        selected = select_topics(records, min_count=2, max_count=3)

        self.assertEqual(selected[0].title, "AI 新产品发布")
        self.assertEqual(selected[0].platforms, ["weibo", "baidu"])
        self.assertEqual(selected[0].ranks, {"weibo": 1, "baidu": 3})

    def test_select_topics_respects_max_count(self):
        records = [
            record("weibo", 1, "话题一"),
            record("weibo", 2, "话题二"),
            record("weibo", 3, "话题三"),
        ]

        selected = select_topics(records, min_count=1, max_count=2)

        self.assertEqual(len(selected), 2)


if __name__ == "__main__":
    unittest.main()
