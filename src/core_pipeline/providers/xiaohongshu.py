from src.core_pipeline.types import DetailEvidence, HotRecord


def collect_xiaohongshu_detail(
    record: HotRecord,
    fetched_at: str,
    session_status: str,
    extracted_notes: list[dict[str, object]],
) -> DetailEvidence:
    if session_status != "ok":
        return _status_evidence(record, fetched_at, session_status)
    if not extracted_notes:
        return _status_evidence(record, fetched_at, "empty_content")
    content = "\n\n".join(str(note.get("content", "")).strip() for note in extracted_notes[:5]).strip()
    comments = []
    for note in extracted_notes[:5]:
        note_comments = note.get("comments_preview", [])
        if isinstance(note_comments, list):
            comments.extend(str(comment) for comment in note_comments[:5])
    return DetailEvidence(
        evidence_id=f"evidence_xiaohongshu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="xiaohongshu",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"小红书笔记详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={"notes": len(extracted_notes)},
        comments_preview=comments[:20],
        result_urls=[str(note.get("url", "")) for note in extracted_notes[:5] if note.get("url")],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="ok",
        error_type=None,
        confidence="medium",
        raw_payload={"notes": extracted_notes},
    )


def _status_evidence(record: HotRecord, fetched_at: str, status: str) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_xiaohongshu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="xiaohongshu",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"小红书笔记详情：{record.title}",
        content="",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=[],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=status,
        confidence="low",
        raw_payload={},
    )


def extract_xiaohongshu_notes_from_text(page_text: str) -> list[dict[str, object]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    chunks: list[dict[str, object]] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if line.startswith("赞 ") or line.startswith("评论 ") or " 收藏 " in line:
            content = "\n".join(current)
            chunks.append({"content": content, "comments_preview": [], "url": ""})
            current = []
    if current:
        chunks.append({"content": "\n".join(current), "comments_preview": [], "url": ""})
    return chunks[:5]