import unittest

from src.core_pipeline.cache_store import CacheStore
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

    def test_collect_topic_details_uses_video_metadata_for_bilibili_without_fetching_page(self):
        record = hot_record("hot_bilibili_001", "bilibili", "视频标题")
        object.__setattr__(record, "url", "https://www.bilibili.com/video/BV123")
        object.__setattr__(record, "desc", "视频简介内容")
        object.__setattr__(record, "raw_payload", {"title": "视频标题", "desc": "视频简介内容", "url": record.url})
        topic = {
            "topic_key": "视频标题",
            "canonical_title": "视频标题",
            "hot_record_ids": ["hot_bilibili_001"],
            "records": [record],
        }

        def page_fetcher(url: str) -> str:
            raise AssertionError("Bilibili video detail should use metadata instead of fetching noisy page HTML")

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=lambda query: [],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
            page_fetcher=page_fetcher,
        )

        video_rows = [row for row in evidence if row.platform == "bilibili" and row.source_method == "video_metadata"]
        self.assertEqual(video_rows[0].fetch_status, "ok")
        self.assertIn("视频标题", video_rows[0].content)
        self.assertIn("视频简介内容", video_rows[0].content)
        self.assertIn("https://www.bilibili.com/video/BV123", video_rows[0].content)
        self.assertNotIn("\ufffd", video_rows[0].content)
        self.assertEqual(video_rows[0].raw_payload["record"]["title"], "视频标题")


    def test_collect_topic_details_fetches_weibo_and_xiaohongshu_when_sessions_are_ok(self):
        topic = {
            "topic_key": "realhotdetail",
            "canonical_title": "real hot detail",
            "hot_record_ids": ["hot_weibo_001"],
            "records": [hot_record("hot_weibo_001", "weibo", "real hot detail")],
        }
        calls = []

        def social_detail_fetcher(platform: str, query: str):
            calls.append((platform, query))
            if platform == "weibo":
                return [{"content": "real weibo discussion body", "comments_preview": ["weibo comment"], "url": "https://weibo.example.com/a"}]
            if platform == "xiaohongshu":
                return [{"content": "real xiaohongshu note body", "comments_preview": ["xhs comment"], "url": "https://xhs.example.com/a"}]
            raise AssertionError(platform)

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=lambda query: [{"title": "baidu detail", "snippet": "baidu detail body", "url": "https://news.example.com/a"}],
            session_status={"weibo": "ok", "xiaohongshu": "ok"},
            social_detail_fetcher=social_detail_fetcher,
        )

        self.assertIn(("weibo", "real hot detail"), calls)
        self.assertIn(("xiaohongshu", "real hot detail"), calls)
        weibo_rows = [row for row in evidence if row.platform == "weibo"]
        xhs_rows = [row for row in evidence if row.platform == "xiaohongshu"]
        self.assertEqual(weibo_rows[0].fetch_status, "ok")
        self.assertIn("real weibo discussion body", weibo_rows[0].content)
        self.assertEqual(xhs_rows[0].fetch_status, "ok")
        self.assertIn("real xiaohongshu note body", xhs_rows[0].content)


def test_collect_topic_details_skips_social_fetch_for_non_detail_platform():
    topic = {
        "topic_key": "zhihutopic",
        "canonical_title": "zhihu topic",
        "hot_record_ids": ["hot_zhihu_001"],
        "records": [hot_record("hot_zhihu_001", "zhihu", "zhihu topic")],
    }

    def social_detail_fetcher(platform: str, query: str):
        raise AssertionError("non-detail platforms must not trigger social detail fetch")

    evidence = collect_topic_details(
        topics=[topic],
        fetched_at="2026-06-22T20:10:00+08:00",
        search_provider=lambda query: [],
        session_status={"weibo": "ok", "xiaohongshu": "ok"},
        social_detail_fetcher=social_detail_fetcher,
        enabled_detail_platforms=("baidu", "weibo", "xiaohongshu", "bilibili", "juejin"),
    )

    assert any(row.platform == "zhihu" and row.source_method == "dailyhot_metadata" for row in evidence)
    assert not any(row.platform == "weibo" for row in evidence)
    assert not any(row.platform == "xiaohongshu" for row in evidence)


def test_collect_topic_details_reuses_detail_cache(tmp_path):
    cache = CacheStore(tmp_path, now=lambda: __import__("datetime").datetime(2026, 6, 23, tzinfo=__import__("datetime").timezone.utc))
    cached = {
        "evidence_id": "evidence_baidu_hot_weibo_001",
        "topic_key": "cachedtopic",
        "related_hot_record_ids": ["hot_weibo_001"],
        "platform": "baidu",
        "source_role": "required",
        "source_method": "search_results",
        "query": "cached topic",
        "url": "",
        "title": "cached title",
        "content": "cached detail body",
        "author": "",
        "published_at": "",
        "metrics": {},
        "comments_preview": [],
        "result_urls": [],
        "raw_snapshot_path": "",
        "screenshot_path": "",
        "fetched_at": "2026-06-23T00:00:00+00:00",
        "fetch_status": "ok",
        "error_type": None,
        "confidence": "medium",
        "raw_payload": {},
    }
    cache.write("detail:baidu:cachedtopic", cached, fetched_at="2026-06-23T00:00:00+00:00")
    topic = {
        "topic_key": "cachedtopic",
        "canonical_title": "cached topic",
        "hot_record_ids": ["hot_weibo_001"],
        "records": [hot_record("hot_weibo_001", "weibo", "cached topic")],
    }

    evidence = collect_topic_details(
        topics=[topic],
        fetched_at="2026-06-23T08:00:00+08:00",
        search_provider=lambda query: (_ for _ in ()).throw(AssertionError("search should not run")),
        session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        cache_store=cache,
    )

    assert any(row.platform == "baidu" and row.content == "cached detail body" for row in evidence)


def test_collect_topic_details_reuses_xiaohongshu_cache(tmp_path):
    cache = CacheStore(tmp_path, now=lambda: __import__("datetime").datetime(2026, 6, 23, tzinfo=__import__("datetime").timezone.utc))
    # Pre-populate Baidu cache to prevent search_provider from being called
    baidu_cached = {
        "evidence_id": "evidence_baidu_hot_weibo_001",
        "topic_key": "cachedtopic",
        "related_hot_record_ids": ["hot_weibo_001"],
        "platform": "baidu",
        "source_role": "required",
        "source_method": "search_results",
        "query": "cached topic",
        "url": "",
        "title": "cached title",
        "content": "cached detail body",
        "author": "",
        "published_at": "",
        "metrics": {},
        "comments_preview": [],
        "result_urls": [],
        "raw_snapshot_path": "",
        "screenshot_path": "",
        "fetched_at": "2026-06-23T00:00:00+00:00",
        "fetch_status": "ok",
        "error_type": None,
        "confidence": "medium",
        "raw_payload": {},
    }
    cache.write("detail:baidu:cachedtopic", baidu_cached, fetched_at="2026-06-23T00:00:00+00:00")
    xiaohongshu_cached = {
        "evidence_id": "evidence_xiaohongshu_topic_001",
        "topic_key": "cachedtopic",
        "related_hot_record_ids": ["hot_weibo_001"],
        "platform": "xiaohongshu",
        "source_role": "required",
        "source_method": "social_detail",
        "query": "cached topic",
        "url": "https://example.com/xhs/123",
        "title": "cached xhs title",
        "content": "cached xhs content",
        "author": "xhs_author",
        "published_at": "2026-06-23T00:00:00+00:00",
        "metrics": {},
        "comments_preview": [],
        "result_urls": [],
        "raw_snapshot_path": "",
        "screenshot_path": "",
        "fetched_at": "2026-06-23T00:00:00+00:00",
        "fetch_status": "ok",
        "error_type": None,
        "confidence": "medium",
        "raw_payload": {},
    }
    cache.write("detail:xiaohongshu:cachedtopic", xiaohongshu_cached, fetched_at="2026-06-23T00:00:00+00:00")
    topic = {
        "topic_key": "cachedtopic",
        "canonical_title": "cached topic",
        "hot_record_ids": ["hot_weibo_001"],
        "records": [hot_record("hot_weibo_001", "weibo", "cached topic")],
    }

    def social_detail_fetcher(platform: str, query: str):
        raise AssertionError("social_detail_fetcher should not be called on cache hit")

    evidence = collect_topic_details(
        topics=[topic],
        fetched_at="2026-06-23T08:00:00+08:00",
        search_provider=lambda query: (_ for _ in ()).throw(AssertionError("search should not run")),
        session_status={"weibo": "login_required", "xiaohongshu": "ok"},
        social_detail_fetcher=social_detail_fetcher,
        cache_store=cache,
    )

    assert any(row.platform == "xiaohongshu" and row.content == "cached xhs content" for row in evidence)


if __name__ == "__main__":
    unittest.main()
