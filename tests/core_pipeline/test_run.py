import unittest

from src.core_pipeline.run import output_paths


class RunTests(unittest.TestCase):
    def test_output_paths_are_fixed(self):
        paths = output_paths()

        self.assertEqual(str(paths["hot_records"]), "data/raw/dailyhot_records.json")
        self.assertEqual(str(paths["detail_evidence"]), "data/evidence/detail_evidence.json")
        self.assertEqual(str(paths["topic_briefs"]), "data/processed/topic_briefs.json")
        self.assertEqual(str(paths["markdown_report"]), "reports/core_platform_topic_digest.md")


from pathlib import Path
import tempfile

from src.core_pipeline.run import run_recent_detail_collection


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
            self.assertTrue((root / "reports/recent_hot_topics_digest.md").exists())


if __name__ == "__main__":
    unittest.main()