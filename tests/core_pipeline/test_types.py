import unittest

from src.core_pipeline.types import (
    DetailEvidence,
    HotRecord,
    RequiredDetailStatus,
    TopicBrief,
    TopicCluster,
)


class TypesTests(unittest.TestCase):
    def test_hot_record_serializes_dailyhot_fields(self):
        record = HotRecord(
            id="hot_weibo_001",
            source="dailyhotapi",
            platform="weibo",
            route="weibo",
            category="core_discovery",
            title="测试热点",
            rank=1,
            hot_value="1000",
            url="https://example.com",
            mobile_url="https://m.example.com",
            desc="摘要",
            author="",
            cover="",
            timestamp="",
            captured_at="2026-06-14T20:00:00+08:00",
            raw_payload={"title": "测试热点"},
            fetch_status="ok",
            error_type=None,
        )

        data = record.to_dict()

        self.assertEqual(data["title"], "测试热点")
        self.assertEqual(data["route"], "weibo")
        self.assertEqual(data["desc"], "摘要")

    def test_detail_evidence_serializes_required_source(self):
        evidence = DetailEvidence(
            evidence_id="evidence_001",
            topic_key="测试热点",
            related_hot_record_ids=["hot_weibo_001"],
            platform="weibo",
            source_role="required",
            source_method="browser_session",
            query="测试热点",
            url="https://example.com/detail",
            title="微博详情",
            content="微博正文",
            author="作者",
            published_at="2026-06-14T18:30:00+08:00",
            metrics={"likes": 1},
            comments_preview=["评论"],
            result_urls=[],
            raw_snapshot_path="data/snapshots/weibo/evidence_001.html",
            screenshot_path="data/screenshots/weibo/evidence_001.png",
            fetched_at="2026-06-14T20:05:00+08:00",
            fetch_status="ok",
            error_type=None,
            confidence="medium",
            raw_payload={},
        )

        data = evidence.to_dict()

        self.assertEqual(data["source_role"], "required")
        self.assertEqual(data["content"], "微博正文")

    def test_required_detail_status_marks_missing_sources(self):
        status = RequiredDetailStatus(
            topic_key="测试热点",
            weibo="ok",
            xiaohongshu="login_required",
            baidu="ok",
            missing_required_details=["xiaohongshu"],
            auxiliary_evidence_count=4,
            detail_completeness="core_incomplete",
        )

        self.assertEqual(status.to_dict()["missing_required_details"], ["xiaohongshu"])

    def test_cluster_and_brief_keep_evidence_links(self):
        cluster = TopicCluster(
            topic_id="topic_001",
            canonical_title="测试热点",
            aliases=["测试事件"],
            hot_record_ids=["hot_weibo_001"],
            evidence_ids=["evidence_001"],
            platforms=["weibo", "baidu"],
            required_detail_status={
                "weibo": "ok",
                "xiaohongshu": "ok",
                "baidu": "ok",
            },
            detail_completeness="complete",
            cluster_confidence="high",
        )
        brief = TopicBrief(
            topic_id="topic_001",
            canonical_title="测试热点",
            summary="事件摘要",
            key_facts=["事实一"],
            platform_observations={"weibo": "微博讨论"},
            evidence_ids=["evidence_001"],
            missing_required_details=[],
            detail_completeness="complete",
            confidence="high",
        )

        self.assertEqual(cluster.to_dict()["evidence_ids"], ["evidence_001"])
        self.assertEqual(brief.to_dict()["detail_completeness"], "complete")


if __name__ == "__main__":
    unittest.main()