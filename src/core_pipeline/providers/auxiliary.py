from src.core_pipeline.types import DetailEvidence, HotRecord


def evidence_from_dailyhot_record(record: HotRecord, fetched_at: str) -> DetailEvidence:
    content_parts = [record.title, record.desc, record.author, record.hot_value]
    content = "\n".join(part for part in content_parts if part)
    return DetailEvidence(
        evidence_id=f"evidence_aux_{record.platform}_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform=record.platform,
        source_role="auxiliary",
        source_method="dailyhotapi",
        query=record.title,
        url=record.url,
        title=f"{record.platform} 辅助证据：{record.title}",
        content=content,
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[record.url] if record.url else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=record.fetch_status,
        error_type=record.error_type,
        confidence="low" if not record.desc else "medium",
        raw_payload=record.raw_payload,
    )