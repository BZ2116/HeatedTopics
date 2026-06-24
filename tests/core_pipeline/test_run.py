import unittest
import json
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.core_pipeline.cache_store import CacheStore
from src.core_pipeline.run import build_creator_topic_index_command, default_social_detail_fetcher, main, output_paths, platform_raw_paths, print_progress, rooted_output_paths
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

    def test_platform_raw_paths_are_separate_by_platform_and_kind(self):
        paths = platform_raw_paths(Path("tmp-root"))

        self.assertEqual(paths["xiaohongshu_topics"].as_posix(), "tmp-root/data/raw/platforms/xiaohongshu_topics.jsonl")
        self.assertEqual(paths["xiaohongshu_notes"].as_posix(), "tmp-root/data/raw/platforms/xiaohongshu_notes.jsonl")
        self.assertEqual(paths["baidu_topics"].as_posix(), "tmp-root/data/raw/platforms/baidu_topics.jsonl")
        self.assertEqual(paths["baidu_details"].as_posix(), "tmp-root/data/raw/platforms/baidu_details.jsonl")
        self.assertEqual(paths["weibo_topics"].as_posix(), "tmp-root/data/raw/platforms/weibo_topics.jsonl")
        self.assertEqual(paths["weibo_posts"].as_posix(), "tmp-root/data/raw/platforms/weibo_posts.jsonl")

    def test_print_progress_writes_numbered_message(self):
        output = StringIO()

        with patch("sys.stdout", output):
            print_progress(3, 8, "去重生成话题：10 个话题")

        self.assertEqual(output.getvalue(), "[3/8] 去重生成话题：10 个话题\n")


    def test_core_hot_details_command_limits_routes_and_detail_platforms(self):
        calls = []

        def fake_run_recent_detail_collection(**kwargs):
            calls.append(kwargs)

        with patch("sys.argv", ["run.py", "collect-core-hot-details", "--window", "today", "--refresh"]):
            with patch("src.core_pipeline.run.run_recent_detail_collection", fake_run_recent_detail_collection):
                main()

        self.assertEqual(calls[0]["routes"], ("baidu", "weibo", "xiaohongshu"))
        self.assertEqual(calls[0]["detail_platforms"], ("baidu", "weibo", "xiaohongshu"))
        self.assertEqual(calls[0]["supplemental_social_platforms"], ("weibo", "xiaohongshu"))
        self.assertEqual(calls[0]["max_hot_per_platform"], 10)
        self.assertTrue(calls[0]["refresh"])

    def test_default_social_detail_fetcher_limits_xiaohongshu_notes_to_twenty(self):
        with patch("src.core_pipeline.run.fetch_social_details_with_browser", return_value={"rows": [], "raw": {}}) as fetcher:
            default_social_detail_fetcher("xiaohongshu", "露营穿搭")

        fetcher.assert_called_once_with("xiaohongshu", "露营穿搭", max_items=20)

    def test_output_paths_include_creator_topic_index_and_report(self):
        paths = output_paths()

        self.assertEqual(paths["creator_topic_index"].as_posix(), "data/processed/creator_topic_index.json")
        self.assertEqual(paths["creator_topic_cards"].as_posix(), "reports/creator_topic_cards.md")

    def test_build_creator_topic_index_command_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/raw").mkdir(parents=True)
            (root / "data/evidence").mkdir(parents=True)
            (root / "data/processed").mkdir(parents=True)
            (root / "data/raw/dailyhot_records.json").write_text(
                json.dumps([
                    {
                        "id": "hot_weibo_001",
                        "platform": "weibo",
                        "title": "河北高考分数线",
                        "rank": 1,
                        "hot_value": "1784276",
                    }
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data/evidence/detail_evidence_raw.jsonl").write_text(
                json.dumps(
                    {
                        "source": "weibo",
                        "title": "河北高考分数线",
                        "content": "河北2026高考分数线公布，本科线、志愿填报成为讨论重点。",
                        "url": "https://example.com/weibo",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "data/processed/topic_clusters.json").write_text(
                json.dumps([
                    {
                        "topic_key": "河北高考分数线",
                        "canonical_title": "河北高考分数线",
                        "hot_record_ids": ["hot_weibo_001"],
                        "platforms": ["weibo"],
                        "best_rank": 1,
                    }
                ], ensure_ascii=False),
                encoding="utf-8",
            )

            result = build_creator_topic_index_command(
                root=root,
                generated_at="2026-06-24T16:00:00+08:00",
                render_report=True,
            )

            index_path = root / "data/processed/creator_topic_index.json"
            report_path = root / "reports/creator_topic_cards.md"
            self.assertEqual(result["topics_count"], 1)
            self.assertTrue(index_path.exists())
            self.assertTrue(report_path.exists())
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(index["topics"][0]["domain_path"], ["教育升学", "高考", "分数线"])
            self.assertIn("河北高考分数线", report_path.read_text(encoding="utf-8"))

    def test_main_wires_build_creator_topic_index_command(self):
        calls = []

        def fake_command(**kwargs):
            calls.append(kwargs)
            return {"topics_count": 0}

        with patch("sys.argv", ["run.py", "build-creator-topic-index", "--render-report"]):
            with patch("src.core_pipeline.run.build_creator_topic_index_command", fake_command):
                main()

        self.assertEqual(calls[0]["root"], Path("."))
        self.assertTrue(calls[0]["render_report"])


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

    def test_run_recent_detail_collection_writes_simplified_raw_rows_with_full_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full_page_text = "\n".join(f"raw page line {index}" for index in range(80))

            run_recent_detail_collection(
                window="today",
                root=root,
                routes=("weibo",),
                route_fetcher=lambda route: {"data": [{"title": "raw shape topic", "hot": "100", "url": "https://example.com/hot", "cover": "https://example.com/cover.jpg"}]},
                search_provider=lambda query: [],
                session_status={"weibo": "ok", "xiaohongshu": "login_required"},
                social_detail_fetcher=lambda platform, query: {
                    "rows": [{"content": "short extracted row", "comments_preview": [], "url": "https://example.com/post"}],
                    "raw": {"page_text": full_page_text},
                },
                page_fetcher=None,
                now=lambda: "2026-06-22T20:00:00+08:00",
                cache_store=CacheStore(root / "cache", refresh=True),
            )

            raw_path = root / "data/evidence/detail_evidence_raw.jsonl"
            rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(set(rows[0]), {"source", "url", "title", "content", "cover", "hotvalue", "rank"})
            self.assertEqual(rows[0]["source"], "weibo")
            self.assertEqual(rows[0]["url"], "https://example.com/post")
            self.assertEqual(rows[0]["title"], "raw shape topic")
            self.assertEqual(rows[0]["content"], full_page_text)
            self.assertEqual(rows[0]["cover"], "https://example.com/cover.jpg")
            self.assertEqual(rows[0]["hotvalue"], "100")
            self.assertEqual(rows[0]["rank"], 1)

    def test_run_recent_detail_collection_writes_platform_raw_files_without_mixing_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def route_fetcher(route: str):
                return {
                    "data": [
                        {
                            "title": f"{route} raw topic",
                            "hot": f"{route}-hot",
                            "url": f"https://example.com/{route}/hot",
                            "cover": f"https://example.com/{route}/cover.jpg",
                        }
                    ]
                }

            def social_detail_fetcher(platform: str, query: str):
                if platform == "xiaohongshu":
                    return {
                        "rows": [
                            {"content": "xhs note 1 full text", "comments_preview": ["xhs comment"], "url": "https://xhs.example/note/1"},
                            {"content": "xhs note 2 full text", "comments_preview": [], "url": "https://xhs.example/note/2"},
                        ],
                        "raw": {
                            "search_url": "https://www.xiaohongshu.com/search_result?keyword=xhs",
                            "current_url": "https://www.xiaohongshu.com/search_result?keyword=xhs",
                            "page_text": "full xiaohongshu browser page text",
                            "dom_rows": [{"content": "xhs dom row"}],
                        },
                    }
                return {
                    "rows": [
                        {"content": "weibo post 1 full text", "comments_preview": ["weibo comment"], "url": "https://weibo.example/post/1"}
                    ],
                    "raw": {
                        "search_url": "https://s.weibo.com/weibo?q=weibo",
                        "current_url": "https://s.weibo.com/weibo?q=weibo",
                        "page_text": "full weibo browser page text",
                        "dom_rows": [{"content": "weibo dom row"}],
                    },
                }

            run_recent_detail_collection(
                window="today",
                root=root,
                routes=("baidu", "weibo", "xiaohongshu"),
                route_fetcher=route_fetcher,
                search_provider=lambda query: [{"title": "baidu result", "snippet": "baidu result full snippet", "url": "https://baidu.example/detail"}],
                session_status={"weibo": "ok", "xiaohongshu": "ok"},
                social_detail_fetcher=social_detail_fetcher,
                page_fetcher=None,
                now=lambda: "2026-06-24T08:00:00+08:00",
                cache_store=CacheStore(root / "cache", refresh=True),
            )

            paths = platform_raw_paths(root)
            xhs_topics = [json.loads(line) for line in paths["xiaohongshu_topics"].read_text(encoding="utf-8").splitlines()]
            xhs_notes = [json.loads(line) for line in paths["xiaohongshu_notes"].read_text(encoding="utf-8").splitlines()]
            baidu_topics = [json.loads(line) for line in paths["baidu_topics"].read_text(encoding="utf-8").splitlines()]
            baidu_details = [json.loads(line) for line in paths["baidu_details"].read_text(encoding="utf-8").splitlines()]
            weibo_topics = [json.loads(line) for line in paths["weibo_topics"].read_text(encoding="utf-8").splitlines()]
            weibo_posts = [json.loads(line) for line in paths["weibo_posts"].read_text(encoding="utf-8").splitlines()]

            self.assertEqual({row["platform"] for row in xhs_topics}, {"xiaohongshu"})
            self.assertEqual({row["platform"] for row in xhs_notes}, {"xiaohongshu"})
            self.assertEqual({row["platform"] for row in baidu_topics}, {"baidu"})
            self.assertEqual({row["platform"] for row in baidu_details}, {"baidu"})
            self.assertEqual({row["platform"] for row in weibo_topics}, {"weibo"})
            self.assertEqual({row["platform"] for row in weibo_posts}, {"weibo"})

            self.assertEqual(xhs_notes[0]["kind"], "notes")
            self.assertEqual(xhs_notes[0]["fetch_status"], "placeholder")
            self.assertEqual(xhs_notes[0]["notes"], [])
            self.assertEqual(xhs_notes[0]["external_detail_status"], "pending")
            self.assertEqual(baidu_details[0]["search_results"][0]["snippet"], "baidu result full snippet")
            self.assertEqual(baidu_details[0]["query_attempts"][0]["results"][0]["title"], "baidu result")
            self.assertEqual(weibo_posts[0]["posts"][0]["content"], "weibo post 1 full text")
            self.assertEqual(weibo_posts[0]["browser_raw"]["dom_rows"][0]["content"], "weibo dom row")

    def test_run_recent_detail_collection_limits_hot_records_per_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured_xhs_limits = []

            def route_fetcher(route: str):
                return {
                    "data": [
                        {"title": f"{route} topic {index}", "hot": str(100 - index), "url": f"https://example.com/{route}/{index}"}
                        for index in range(12)
                    ]
                }

            def xiaohongshu_hot_fetcher(captured_at: str, max_items: int = 20):
                captured_xhs_limits.append(max_items)
                from src.core_pipeline.types import HotRecord

                return [
                    HotRecord(
                        id=f"hot_xhs_{index:03d}",
                        source="xiaohongshu_rank",
                        platform="xiaohongshu",
                        route="xiaohongshu",
                        category="core_discovery",
                        title=f"xhs topic {index}",
                        rank=index,
                        hot_value=str(100 - index),
                        url=f"https://example.com/xhs/{index}",
                        mobile_url="",
                        desc="",
                        author="",
                        cover="",
                        timestamp="",
                        captured_at=captured_at,
                        raw_payload={},
                        fetch_status="ok",
                        error_type=None,
                    )
                    for index in range(1, max_items + 1)
                ]

            result = run_recent_detail_collection(
                window="today",
                root=root,
                routes=("baidu", "weibo", "xiaohongshu"),
                route_fetcher=lambda route: {"data": []} if route == "xiaohongshu" else route_fetcher(route),
                search_provider=lambda query: [],
                session_status={"weibo": "login_required", "xiaohongshu": "ok"},
                page_fetcher=None,
                social_detail_fetcher=None,
                xiaohongshu_hot_fetcher=xiaohongshu_hot_fetcher,
                now=lambda: "2026-06-24T08:00:00+08:00",
                cache_store=CacheStore(root / "cache", refresh=True),
                max_hot_per_platform=10,
            )

            records = json.loads((root / "data/raw/dailyhot_records.json").read_text(encoding="utf-8"))
            ok_records = [record for record in records if record["fetch_status"] == "ok"]
            counts = {
                platform: sum(1 for record in ok_records if record["platform"] == platform)
                for platform in ("baidu", "weibo", "xiaohongshu")
            }

            self.assertEqual(counts, {"baidu": 10, "weibo": 10, "xiaohongshu": 10})
            self.assertEqual(captured_xhs_limits, [10])
            self.assertEqual(result["hot_records_count"], 30)

    def test_run_recent_detail_collection_fetches_xiaohongshu_hot_records_without_login_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []

            def xiaohongshu_hot_fetcher(captured_at: str, max_items: int = 20):
                calls.append(max_items)
                from src.core_pipeline.types import HotRecord

                return [
                    HotRecord(
                        id="hot_xiaohongshu_rank_001",
                        source="xiaohongshu_rank",
                        platform="xiaohongshu",
                        route="xiaohongshu",
                        category="core_discovery",
                        title="xhs rank topic",
                        rank=1,
                        hot_value="99w",
                        url="https://example.com/xhs",
                        mobile_url="",
                        desc="",
                        author="",
                        cover="",
                        timestamp="",
                        captured_at=captured_at,
                        raw_payload={},
                        fetch_status="ok",
                        error_type=None,
                    )
                ]

            result = run_recent_detail_collection(
                window="today",
                root=root,
                routes=("xiaohongshu",),
                route_fetcher=lambda route: {"data": []},
                search_provider=lambda query: [],
                session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
                xiaohongshu_hot_fetcher=xiaohongshu_hot_fetcher,
                now=lambda: "2026-06-24T08:00:00+08:00",
                cache_store=CacheStore(root / "cache", refresh=True),
                max_hot_per_platform=10,
            )

            self.assertEqual(calls, [10])
            self.assertEqual(result["hot_records_count"], 1)
            records = json.loads((root / "data/raw/dailyhot_records.json").read_text(encoding="utf-8"))
            self.assertEqual(records[0]["platform"], "xiaohongshu")
            self.assertEqual(records[0]["fetch_status"], "ok")

    def test_run_recent_detail_collection_replaces_failed_xiaohongshu_route_with_rank_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def xiaohongshu_hot_fetcher(captured_at: str, max_items: int = 20):
                from src.core_pipeline.types import HotRecord

                return [
                    HotRecord(
                        id="hot_xiaohongshu_rank_001",
                        source="xiaohongshu_rank",
                        platform="xiaohongshu",
                        route="xiaohongshu",
                        category="core_discovery",
                        title="xhs fallback topic",
                        rank=1,
                        hot_value="99w",
                        url="https://example.com/xhs",
                        mobile_url="",
                        desc="",
                        author="",
                        cover="",
                        timestamp="",
                        captured_at=captured_at,
                        raw_payload={},
                        fetch_status="ok",
                        error_type=None,
                    )
                ]

            run_recent_detail_collection(
                window="today",
                root=root,
                routes=("xiaohongshu",),
                route_fetcher=lambda route: (_ for _ in ()).throw(RuntimeError("route failed")),
                search_provider=lambda query: [],
                session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
                xiaohongshu_hot_fetcher=xiaohongshu_hot_fetcher,
                now=lambda: "2026-06-24T08:00:00+08:00",
                cache_store=CacheStore(root / "cache", refresh=True),
                max_hot_per_platform=10,
            )

            records = json.loads((root / "data/raw/dailyhot_records.json").read_text(encoding="utf-8"))
            self.assertEqual([record["fetch_status"] for record in records], ["ok"])

    def test_run_recent_detail_collection_falls_back_to_weibo_hot_records_when_dailyhot_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []

            def weibo_hot_fetcher(captured_at: str, max_items: int = 50):
                calls.append(max_items)
                from src.core_pipeline.types import HotRecord

                return [
                    HotRecord(
                        id=f"hot_weibo_browser_{index:03d}",
                        source="weibo_browser_hot",
                        platform="weibo",
                        route="weibo",
                        category="core_discovery",
                        title=f"weibo hot topic {index}",
                        rank=index,
                        hot_value=str(1000 - index),
                        url=f"https://s.weibo.com/weibo?q=topic{index}",
                        mobile_url="",
                        desc="",
                        author="微博热搜",
                        cover="",
                        timestamp="",
                        captured_at=captured_at,
                        raw_payload={},
                        fetch_status="ok",
                        error_type=None,
                    )
                    for index in range(1, max_items + 1)
                ]

            result = run_recent_detail_collection(
                window="today",
                root=root,
                routes=("weibo",),
                route_fetcher=lambda route: {"data": []},
                search_provider=lambda query: [],
                session_status={"weibo": "ok", "xiaohongshu": "login_required"},
                weibo_hot_fetcher=weibo_hot_fetcher,
                social_detail_fetcher=lambda platform, query: [{"content": "post body", "comments_preview": [], "url": ""}],
                now=lambda: "2026-06-24T08:00:00+08:00",
                cache_store=CacheStore(root / "cache", refresh=True),
                max_hot_per_platform=10,
            )

            records = json.loads((root / "data/raw/dailyhot_records.json").read_text(encoding="utf-8"))
            self.assertEqual(calls, [10])
            self.assertEqual(sum(1 for record in records if record["platform"] == "weibo"), 10)
            self.assertEqual(result["hot_records_count"], 10)

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
            routes=("xiaohongshu",),
            route_fetcher=lambda route: {"data": [{"title": "single session topic", "hot": "100", "url": "https://example.com/hot"}]},
            search_provider=lambda query: [{"title": "baidu detail", "snippet": "baidu detail body", "url": "https://news.example.com/a"}],
            session_status={"weibo": "login_required", "xiaohongshu": "ok"},
            social_detail_fetcher=social_detail_fetcher,
            page_fetcher=None,
            now=lambda: "2026-06-22T20:00:00+08:00",
            cache_store=CacheStore(Path(tempfile.mkdtemp()), refresh=True),
        )

        self.assertEqual(result["missing_browser_sessions_count"], 1)
        self.assertEqual(calls, [])

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

    def test_run_recent_detail_collection_adds_xiaohongshu_browser_hot_records_when_dailyhot_is_empty(self):
        calls = []

        def route_fetcher(route: str):
            if route == "baidu":
                return {"data": [{"title": "baidu seed topic", "hot": "100"}]}
            if route == "xiaohongshu":
                return {"data": []}
            return {"data": []}

        def xiaohongshu_hot_fetcher(captured_at: str):
            calls.append(captured_at)
            from src.core_pipeline.types import HotRecord

            return [
                HotRecord(
                    id="hot_xiaohongshu_browser_001",
                    source="xiaohongshu_browser",
                    platform="xiaohongshu",
                    route="xiaohongshu",
                    category="core_discovery",
                    title="xhs browser hot topic",
                    rank=1,
                    hot_value="",
                    url="https://www.xiaohongshu.com/explore/1",
                    mobile_url="",
                    desc="raw xhs card text",
                    author="",
                    cover="",
                    timestamp="",
                    captured_at=captured_at,
                    raw_payload={"page_text": "raw xhs explore"},
                    fetch_status="ok",
                    error_type=None,
                )
            ]

        result = run_recent_detail_collection(
            window="today",
            routes=("baidu", "xiaohongshu"),
            route_fetcher=route_fetcher,
            search_provider=lambda query: [{"title": "detail", "snippet": "body", "url": "https://example.com"}],
            session_status={"weibo": "login_required", "xiaohongshu": "ok"},
            social_detail_fetcher=lambda platform, query: {"rows": [{"content": "xhs detail", "comments_preview": [], "url": ""}], "raw": {}},
            xiaohongshu_hot_fetcher=xiaohongshu_hot_fetcher,
            now=lambda: "2026-06-24T08:00:00+08:00",
            cache_store=CacheStore(Path(tempfile.mkdtemp()), refresh=True),
        )

        assert calls == ["2026-06-24T08:00:00+08:00"]
        assert result["hot_records_count"] == 2
        assert result["topics_count"] == 2


if __name__ == "__main__":
    unittest.main()
