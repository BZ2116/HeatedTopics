import unittest

from src.core_pipeline.topic_clusterer import cluster_topics
from src.core_pipeline.types import DetailEvidence, HotRecord


def hot(record_id: str, title: str, platform: str) -> HotRecord:
    return HotRecord(record_id, "dailyhotapi", platform, platform, "core_discovery", title, 1, "", "", "", "", "", "", "", "2026-06-14T20:00:00+08:00", {}, "ok", None)


def ev(evidence_id: str, title: str, platform: str) -> DetailEvidence:
    return DetailEvidence(evidence_id, title, ["hot_001"], platform, "required", "test", title, "", title, "内容", "", "", {}, [], [], "", "", "2026-06-14T20:10:00+08:00", "ok", None, "medium", {})


class TopicClustererTests(unittest.TestCase):
    def test_same_normalized_title_merges_records_and_evidence(self):
        clusters = cluster_topics(
            [hot("hot_001", "测试 热点", "weibo"), hot("hot_002", "测试热点", "baidu")],
            [ev("evidence_001", "测试热点", "weibo")],
        )

        self.assertEqual(len(clusters), 1)
        self.assertEqual(sorted(clusters[0].hot_record_ids), ["hot_001", "hot_002"])
        self.assertEqual(clusters[0].evidence_ids, ["evidence_001"])


if __name__ == "__main__":
    unittest.main()