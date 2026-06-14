import unittest

from src.core_pipeline.brief_generator import generate_topic_brief
from src.core_pipeline.types import DetailEvidence, TopicCluster


class BriefGeneratorTests(unittest.TestCase):
    def test_brief_uses_evidence_and_marks_missing_required_sources(self):
        cluster = TopicCluster(
            topic_id="topic_001",
            canonical_title="测试热点",
            aliases=["测试热点"],
            hot_record_ids=["hot_001"],
            evidence_ids=["evidence_001"],
            platforms=["weibo"],
            required_detail_status={"weibo": "ok", "xiaohongshu": "login_required", "baidu": "ok"},
            detail_completeness="core_incomplete",
            cluster_confidence="low",
        )
        evidence = DetailEvidence(
            "evidence_001",
            "测试热点",
            ["hot_001"],
            "weibo",
            "required",
            "test",
            "测试热点",
            "",
            "微博详情",
            "微博正文内容",
            "",
            "",
            {},
            ["评论"],
            [],
            "",
            "",
            "2026-06-14T20:10:00+08:00",
            "ok",
            None,
            "medium",
            {},
        )

        brief = generate_topic_brief(cluster, [evidence])

        self.assertEqual(brief.missing_required_details, ["xiaohongshu"])
        self.assertIn("微博正文内容", brief.summary)


if __name__ == "__main__":
    unittest.main()