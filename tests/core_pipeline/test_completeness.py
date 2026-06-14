import unittest

from src.core_pipeline.completeness import evaluate_required_details
from src.core_pipeline.types import DetailEvidence


def evidence(platform: str, role: str, status: str) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_{platform}",
        topic_key="测试热点",
        related_hot_record_ids=["hot_001"],
        platform=platform,
        source_role=role,
        source_method="test",
        query="测试热点",
        url="",
        title="",
        content="内容" if status == "ok" else "",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=[],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at="2026-06-14T20:10:00+08:00",
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium",
        raw_payload={},
    )


class CompletenessTests(unittest.TestCase):
    def test_complete_when_required_three_sources_are_ok(self):
        result = evaluate_required_details(
            "测试热点",
            [
                evidence("weibo", "required", "ok"),
                evidence("xiaohongshu", "required", "ok"),
                evidence("baidu", "required", "ok"),
                evidence("github", "auxiliary", "ok"),
            ],
        )

        self.assertEqual(result.detail_completeness, "complete")
        self.assertEqual(result.auxiliary_evidence_count, 1)

    def test_missing_xiaohongshu_marks_core_incomplete(self):
        result = evaluate_required_details(
            "测试热点",
            [
                evidence("weibo", "required", "ok"),
                evidence("xiaohongshu", "required", "login_required"),
                evidence("baidu", "required", "ok"),
            ],
        )

        self.assertEqual(result.detail_completeness, "core_incomplete")
        self.assertEqual(result.missing_required_details, ["xiaohongshu"])


if __name__ == "__main__":
    unittest.main()