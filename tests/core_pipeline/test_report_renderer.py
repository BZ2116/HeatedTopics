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


if __name__ == "__main__":
    unittest.main()