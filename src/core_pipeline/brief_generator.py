from src.core_pipeline.types import DetailEvidence, TopicBrief, TopicCluster


def generate_topic_brief(cluster: TopicCluster, evidence_rows: list[DetailEvidence]) -> TopicBrief:
    evidence_by_id = {evidence.evidence_id: evidence for evidence in evidence_rows}
    selected = [
        evidence_by_id[evidence_id]
        for evidence_id in cluster.evidence_ids
        if evidence_id in evidence_by_id
    ]
    ok_evidence = [evidence for evidence in selected if evidence.fetch_status == "ok" and evidence.content]
    summary_text = "；".join(evidence.content[:80] for evidence in ok_evidence[:3])
    if not summary_text:
        summary_text = "核心详情未采集到可用正文。"
    missing = [
        platform
        for platform, status in cluster.required_detail_status.items()
        if status != "ok"
    ]
    observations = {
        evidence.platform: evidence.content[:120]
        for evidence in ok_evidence
    }
    key_facts = [evidence.title for evidence in ok_evidence[:5] if evidence.title]
    return TopicBrief(
        topic_id=cluster.topic_id,
        canonical_title=cluster.canonical_title,
        summary=summary_text,
        key_facts=key_facts,
        platform_observations=observations,
        evidence_ids=cluster.evidence_ids,
        missing_required_details=missing,
        detail_completeness=cluster.detail_completeness,
        confidence=cluster.cluster_confidence,
    )