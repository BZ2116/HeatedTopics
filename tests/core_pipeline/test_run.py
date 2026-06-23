import unittest
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.core_pipeline.cache_store import CacheStore
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


    def test_run_recent_detail_collection_defaults_to_all_registered_dailyhot_routes(self):
        called_routes = []

        def route_fetcher(route: str):
            called_routes.append(route)
            return {"data": []}

        run_recent_detail_collection(
            window="today",
            route_fetcher=route_fetcher,
            search_provider=lambda query: [],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
            page_fetcher=None,
            now=lambda: "2026-06-22T20:00:00+08:00",
            cache_store=CacheStore(Path(tempfile.mkdtemp()), refresh=True),
        )

        self.assertIn("weibo", called_routes)
        self.assertIn("baidu", called_routes)
        self.assertIn("zhihu", called_routes)
        self.assertIn("sina-news", called_routes)
        self.assertIn("github", called_routes)

    def test_run_recent_detail_collection_continues_when_browser_sessions_are_missing(self):
        events = []

        with patch(
            "src.core_pipeline.run.check_required_sessions",
            return_value={"weibo": "login_required", "xiaohongshu": "login_required"},
        ):
            result = run_recent_detail_collection(
                window="today",
                route_fetcher=lambda route: {"data": [{"title": "partial session topic", "hot": "100", "url": "https://example.com/hot"}]},
                search_provider=lambda query: [{"title": "baidu detail", "snippet": "baidu detail body", "url": "https://news.example.com/a"}],
                page_fetcher=None,
                now=lambda: "2026-06-22T20:00:00+08:00",
                progress=lambda current, total, message: events.append((current, total, message)),
            )

        self.assertGreater(result["topics_count"], 0)
        self.assertEqual(result["missing_browser_sessions_count"], 2)
        self.assertTrue(any("weibo" in message and "xiaohongshu" in message for _, _, message in events))

    def test_run_recent_detail_collection_uses_available_single_browser_session(self):
        calls = []

        def social_detail_fetcher(platform: str, query: str):
            calls.append((platform, query))
            return [{"content": f"{platform} real detail", "comments_preview": [], "url": f"https://example.com/{platform}"}]

        result = run_recent_detail_collection(
            window="today",
            routes=("weibo",),
            route_fetcher=lambda route: {"data": [{"title": "single session topic", "hot": "100", "url": "https://example.com/hot"}]},
            search_provider=lambda query: [{"title": "baidu detail", "snippet": "baidu detail body", "url": "https://news.example.com/a"}],
            session_status={"weibo": "login_required", "xiaohongshu": "ok"},
            social_detail_fetcher=social_detail_fetcher,
            page_fetcher=None,
            now=lambda: "2026-06-22T20:00:00+08:00",
            cache_store=CacheStore(Path(tempfile.mkdtemp()), refresh=True),
        )

        self.assertEqual(result["missing_browser_sessions_count"], 1)
        self.assertEqual(calls, [("xiaohongshu", "single session topic")])

    def test_run_recent_detail_collection_passes_cache_to_dailyhot_and_details(self):
        cache = CacheStore(tmp_path := Path(tempfile.mkdtemp()))
        result = run_recent_detail_collection(
            window="today",
            root=tmp_path,
            routes=("weibo",),
            route_fetcher=lambda route: {"data": [{"title": "cache wire topic", "hot": "100"}]},
            search_provider=lambda query: [{"title": "detail", "snippet": "body", "url": "https://example.com"}],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
            cache_store=cache,
            now=lambda: "2026-06-23T08:00:00+08:00",
        )

        assert result["topics_count"] == 1


if __name__ == "__main__":
    unittest.main()
