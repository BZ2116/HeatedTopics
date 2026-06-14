import unittest

from src.core_pipeline.providers.baidu import collect_baidu_detail
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.types import HotRecord


def hot_record(title: str = "测试热点") -> HotRecord:
    return HotRecord(
        id="hot_weibo_001",
        source="dailyhotapi",
        platform="weibo",
        route="weibo",
        category="core_discovery",
        title=title,
        rank=1,
        hot_value="1000",
        url="https://example.com/search",
        mobile_url="",
        desc="DailyHot 摘要",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-14T20:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )


class RequiredProviderTests(unittest.TestCase):
    def test_baidu_detail_uses_search_results_as_required_evidence(self):
        evidence = collect_baidu_detail(
            hot_record(),
            fetched_at="2026-06-14T20:10:00+08:00",
            search_results=[
                {
                    "title": "测试热点 官方回应",
                    "url": "https://news.example.com/a",
                    "snippet": "官方回应内容摘要",
                }
            ],
        )

        self.assertEqual(evidence.platform, "baidu")
        self.assertEqual(evidence.source_role, "required")
        self.assertEqual(evidence.fetch_status, "ok")
        self.assertIn("官方回应内容摘要", evidence.content)

    def test_weibo_missing_session_returns_login_required_evidence(self):
        evidence = collect_weibo_detail(
            hot_record(),
            fetched_at="2026-06-14T20:10:00+08:00",
            session_status="login_required",
            extracted_posts=[],
        )

        self.assertEqual(evidence.fetch_status, "login_required")
        self.assertEqual(evidence.error_type, "login_required")

    def test_xiaohongshu_empty_posts_returns_empty_content(self):
        evidence = collect_xiaohongshu_detail(
            hot_record("小红书热点"),
            fetched_at="2026-06-14T20:10:00+08:00",
            session_status="ok",
            extracted_notes=[],
        )

        self.assertEqual(evidence.fetch_status, "empty_content")
        self.assertEqual(evidence.platform, "xiaohongshu")


if __name__ == "__main__":
    unittest.main()