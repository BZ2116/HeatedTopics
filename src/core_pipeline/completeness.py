from src.core_pipeline.source_registry import REQUIRED_DETAIL_PLATFORMS
from src.core_pipeline.types import DetailEvidence, RequiredDetailStatus


def evaluate_required_details(topic_key: str, evidence_rows: list[DetailEvidence]) -> RequiredDetailStatus:
    status_by_platform = {platform: "failed" for platform in REQUIRED_DETAIL_PLATFORMS}
    auxiliary_count = 0
    for evidence in evidence_rows:
        if evidence.source_role == "auxiliary" and evidence.fetch_status == "ok":
            auxiliary_count += 1
        if evidence.platform in status_by_platform and evidence.source_role == "required":
            status_by_platform[evidence.platform] = evidence.fetch_status
    missing = [
        platform
        for platform in REQUIRED_DETAIL_PLATFORMS
        if status_by_platform[platform] != "ok"
    ]
    if not evidence_rows:
        completeness = "failed"
    elif len(missing) == len(REQUIRED_DETAIL_PLATFORMS) and auxiliary_count > 0:
        completeness = "auxiliary_only"
    elif missing:
        completeness = "core_incomplete"
    else:
        completeness = "complete"
    return RequiredDetailStatus(
        topic_key=topic_key,
        weibo=status_by_platform["weibo"],
        xiaohongshu=status_by_platform["xiaohongshu"],
        baidu=status_by_platform["baidu"],
        missing_required_details=missing,
        auxiliary_evidence_count=auxiliary_count,
        detail_completeness=completeness,
    )