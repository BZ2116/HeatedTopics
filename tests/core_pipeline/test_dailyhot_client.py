import unittest

from src.core_pipeline.dailyhot_client import normalize_dailyhot_response


class DailyHotClientTests(unittest.TestCase):
    def test_normalize_dailyhot_response_preserves_desc_and_urls(self):
        payload = {
            "name": "baidu",
            "data": [
                {
                    "id": 1,
                    "title": "百度热点",
                    "url": "https://top.baidu.com/item",
                    "mobileUrl": "https://m.baidu.com/item",
                    "desc": "百度摘要",
                    "hot": "100",
                    "cover": "https://image.example.com/a.png",
                    "author": "来源",
                    "timestamp": "1780000000000",
                }
            ],
        }

        records = normalize_dailyhot_response("baidu", payload, "2026-06-14T20:00:00+08:00")

        self.assertEqual(records[0].id, "hot_baidu_001")
        self.assertEqual(records[0].category, "core_discovery")
        self.assertEqual(records[0].desc, "百度摘要")
        self.assertEqual(records[0].mobile_url, "https://m.baidu.com/item")

    def test_normalize_unknown_route_marks_unknown_category(self):
        payload = {"name": "unknown", "data": [{"title": "未知热点"}]}

        records = normalize_dailyhot_response("unknown", payload, "2026-06-14T20:00:00+08:00")

        self.assertEqual(records[0].category, "unknown")
        self.assertEqual(records[0].fetch_status, "ok")


from src.core_pipeline.dailyhot_client import collect_dailyhot_records


class DailyHotCollectionTests(unittest.TestCase):
    def test_collect_dailyhot_records_collects_multiple_routes(self):
        payloads = {
            "weibo": {"data": [{"title": "微博热点", "hot": "100"}]},
            "baidu": {"data": [{"title": "百度热点", "hot": "90"}]},
        }

        def fetcher(route: str):
            return payloads[route]

        records = collect_dailyhot_records(
            routes=("weibo", "baidu"),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=fetcher,
        )

        self.assertEqual([record.title for record in records], ["微博热点", "百度热点"])

    def test_collect_dailyhot_records_records_route_failures(self):
        def fetcher(route: str):
            raise RuntimeError("network down")

        records = collect_dailyhot_records(
            routes=("weibo",),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=fetcher,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id, "hot_weibo_failed")
        self.assertEqual(records[0].fetch_status, "failed")
        self.assertEqual(records[0].error_type, "RuntimeError")


if __name__ == "__main__":
    unittest.main()