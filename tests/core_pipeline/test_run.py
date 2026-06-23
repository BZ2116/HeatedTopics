import unittest
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.core_pipeline.run import output_paths, print_progress, rooted_output_paths
from src.core_pipeline.run import run_recent_detail_collection


class RunTests(unittest.TestCase):
    def test_output_paths_are_fixed(self):
        paths = output_paths()

        self.assertEqual(paths["hot_records"].as_posix(), "data/raw/dailyhot_records.json")
        self.assertEqual(paths["detail_evidence"].as_posix(), "data/evidence/detail_evidence.json")
        self.assertEqual(paths["topic_briefs"].as_posix(), "data/processed/topic_briefs.json")
        self.assertEqual(paths["markdown_report"].as_posix(), "reports/core_platform_topic_digest.md")
        self.assertEqual(paths["raw_detail_evidence"].as_posix(), "data/evidence/detail_evidence_raw.jsonl")

    def test_rooted_output_paths_include_raw_jsonl(self):
        paths = rooted_output_paths(Path("tmp-root"))

        self.assertEqual(paths["raw_detail_evidence"].as_posix(), "tmp-root/data/evidence/detail_evidence_raw.jsonl")

    def test_print_progress_writes_numbered_message(self):
        output = StringIO()

        with patch("sys.stdout", output):
            print_progress(3, 8, "去重生成话题：10 个话题")

        self.assertEqual(output.getvalue(), "[3/8] 去重生成话题：10 个话题\n")


class RecentDetailRunTests(unittest.TestCase):
    def test_run_recent_detail_collection_writes_hot_records_evidence_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def route_fetcher(route: str):
                return {"data": [{"title": "某事件", "hot": "100", "url": "https://example.com/hot"}]}

            def search_provider(query: str):
                return [{"title": "某事件详情", "snippet": "详细内容", "url": "https://example.com/detail"}]

            result = run_recent_detail_collection(
                window="today",
                root=root,
                routes=("weibo",),
                route_fetcher=route_fetcher,
                search_provider=search_provider,
                session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
                now=lambda: "2026-06-22T20:00:00+08:00",
            )

            self.assertEqual(result["topics_count"], 1)
            self.assertTrue((root / "data/raw/dailyhot_records.json").exists())
            self.assertTrue((root / "data/evidence/detail_evidence.json").exists())
            self.assertTrue((root / "data/evidence/detail_evidence_raw.jsonl").exists())
            self.assertTrue((root / "reports/recent_hot_topics_digest.md").exists())

    def test_run_recent_detail_collection_reports_progress_steps(self):
        events = []

        def route_fetcher(route: str):
            return {"data": [{"title": "进度测试热点", "hot": "100", "url": "https://example.com/hot"}]}

        run_recent_detail_collection(
            window="today",
            routes=("weibo",),
            route_fetcher=route_fetcher,
            search_provider=lambda query: [],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
            page_fetcher=None,
            now=lambda: "2026-06-22T20:00:00+08:00",
            progress=lambda current, total, message: events.append((current, total, message)),
        )

        self.assertEqual(events[0], (1, 8, "校验采集窗口"))
        self.assertEqual(events[-1][0:2], (8, 8))
        self.assertIn("完成", events[-1][2])
        self.assertIn((2, 8, "采集热榜：weibo"), events)
        self.assertTrue(any("去重生成话题" in message for _, _, message in events))
        self.assertTrue(any("写入 JSON / JSONL" in message for _, _, message in events))


if __name__ == "__main__":
    unittest.main()
