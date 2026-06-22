import unittest

from src.core_pipeline.report_renderer import render_markdown_report
from src.core_pipeline.types import TopicBrief


class ReportRendererTests(unittest.TestCase):
    def test_report_shows_completeness_and_missing_sources(self):
        brief = TopicBrief(
            topic_id="topic_001",
            canonical_title="测试热点",
            summary="摘要",
            key_facts=["事实一"],
            platform_observations={"weibo": "微博观察"},
            evidence_ids=["evidence_001"],
            missing_required_details=["xiaohongshu"],
            detail_completeness="core_incomplete",
            confidence="low",
        )

        markdown = render_markdown_report([brief], generated_at="2026-06-14T21:00:00+08:00")

        self.assertIn("# 核心平台热点详情汇总", markdown)
        self.assertIn("core_incomplete", markdown)
        self.assertIn("xiaohongshu", markdown)


from src.core_pipeline.report_renderer import render_recent_hot_topics_report
from src.core_pipeline.types import DetailEvidence, HotRecord


class RecentHotTopicsReportTests(unittest.TestCase):
    def test_recent_report_shows_detail_status_and_snippet(self):
        record = HotRecord(
            id="hot_weibo_001",
            source="dailyhotapi",
            platform="weibo",
            route="weibo",
            category="core_discovery",
            title="某事件",
            rank=1,
            hot_value="100",
            url="https://example.com/hot",
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
        evidence = DetailEvidence(
            evidence_id="evidence_baidu_hot_weibo_001",
            topic_key="某事件",
            related_hot_record_ids=["hot_weibo_001"],
            platform="baidu",
            source_role="required",
            source_method="search_results",
            query="某事件 怎么回事",
            url="https://example.com/detail",
            title="某事件详情",
            content="这里是详细内容",
            author="",
            published_at="",
            metrics={},
            comments_preview=[],
            result_urls=["https://example.com/detail"],
            raw_snapshot_path="",
            screenshot_path="",
            fetched_at="2026-06-22T20:10:00+08:00",
            fetch_status="ok",
            error_type=None,
            confidence="medium",
            raw_payload={},
        )

        markdown = render_recent_hot_topics_report(
            topics=[{"topic_key": "某事件", "canonical_title": "某事件", "hot_record_ids": ["hot_weibo_001"], "records": [record]}],
            evidence_rows=[evidence],
            generated_at="2026-06-22T20:20:00+08:00",
            window="today",
        )

        self.assertIn("# 近期热点详情汇总", markdown)
        self.assertIn("采集窗口：`today`", markdown)
        self.assertIn("这里是详细内容", markdown)
        self.assertIn("baidu：`ok`", markdown)

    def test_recent_report_matches_evidence_by_topic_key(self):
        record = HotRecord(
            id="hot_weibo_001",
            source="dailyhotapi",
            platform="weibo",
            route="weibo",
            category="core_discovery",
            title="某事件 爆",
            rank=1,
            hot_value="100",
            url="https://example.com/hot",
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
        evidence = DetailEvidence(
            evidence_id="evidence_source_hot_weibo_001",
            topic_key="某事件",
            related_hot_record_ids=["hot_weibo_001"],
            platform="weibo",
            source_role="required",
            source_method="source_url",
            query="某事件 爆",
            url="https://example.com/hot",
            title="某事件 爆",
            content="按规范化 topic_key 关联到的详情内容",
            author="",
            published_at="",
            metrics={},
            comments_preview=[],
            result_urls=["https://example.com/hot"],
            raw_snapshot_path="",
            screenshot_path="",
            fetched_at="2026-06-22T20:10:00+08:00",
            fetch_status="ok",
            error_type=None,
            confidence="medium",
            raw_payload={},
        )

        markdown = render_recent_hot_topics_report(
            topics=[{"topic_key": "某事件", "canonical_title": "某事件 爆", "hot_record_ids": ["hot_weibo_001"], "records": [record]}],
            evidence_rows=[evidence],
            generated_at="2026-06-22T20:20:00+08:00",
            window="today",
        )

        self.assertIn("有详情话题数量：`1`", markdown)
        self.assertIn("按规范化 topic_key 关联到的详情内容", markdown)


if __name__ == "__main__":
    unittest.main()
