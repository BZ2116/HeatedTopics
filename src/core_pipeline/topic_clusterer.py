import re

from src.core_pipeline.completeness import evaluate_required_details
from src.core_pipeline.types import DetailEvidence, HotRecord, TopicCluster


def _topic_key(title: str) -> str:
    return re.sub(r"\s+", "", title).lower()


def cluster_topics(records: list[HotRecord], evidence_rows: list[DetailEvidence]) -> list[TopicCluster]:
    buckets: dict[str, dict[str, object]] = {}
    for record in records:
        key = _topic_key(record.title)
        bucket = buckets.setdefault(key, {"titles": [], "records": [], "evidence": []})
        bucket["titles"].append(record.title)
        bucket["records"].append(record)
    for evidence in evidence_rows:
        key = _topic_key(evidence.topic_key)
        bucket = buckets.setdefault(key, {"titles": [], "records": [], "evidence": []})
        bucket["titles"].append(evidence.topic_key)
        bucket["evidence"].append(evidence)
    clusters: list[TopicCluster] = []
    for index, bucket in enumerate(buckets.values(), start=1):
        bucket_records = bucket["records"]
        bucket_evidence = bucket["evidence"]
        titles = [str(title) for title in bucket["titles"] if str(title)]
        canonical_title = titles[0] if titles else f"topic_{index:03d}"
        completeness = evaluate_required_details(canonical_title, bucket_evidence)
        platforms = sorted(
            {
                item.platform
                for item in list(bucket_records) + list(bucket_evidence)
            }
        )
        clusters.append(
            TopicCluster(
                topic_id=f"topic_{index:03d}",
                canonical_title=canonical_title,
                aliases=sorted(set(titles)),
                hot_record_ids=[record.id for record in bucket_records],
                evidence_ids=[evidence.evidence_id for evidence in bucket_evidence],
                platforms=platforms,
                required_detail_status={
                    "weibo": completeness.weibo,
                    "xiaohongshu": completeness.xiaohongshu,
                    "baidu": completeness.baidu,
                },
                detail_completeness=completeness.detail_completeness,
                cluster_confidence="high" if completeness.detail_completeness == "complete" else "low",
            )
        )
    return clusters