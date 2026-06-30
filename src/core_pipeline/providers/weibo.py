from src.core_pipeline.types import DetailEvidence, HotRecord


def collect_weibo_detail(
    record: HotRecord,
    fetched_at: str,
    session_status: str,
    extracted_posts: list[dict[str, object]],
) -> DetailEvidence:
    if session_status != "ok":
        return _status_evidence(record, fetched_at, session_status)
    if not extracted_posts:
        return _status_evidence(record, fetched_at, "empty_content")
    content = "\n\n".join(str(post.get("content", "")).strip() for post in extracted_posts[:5]).strip()
    comments = []
    for post in extracted_posts[:5]:
        post_comments = post.get("comments_preview", [])
        if isinstance(post_comments, list):
            comments.extend(str(comment) for comment in post_comments[:5])
    return DetailEvidence(
        evidence_id=f"evidence_weibo_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="weibo",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"微博讨论详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={"posts": len(extracted_posts)},
        comments_preview=comments[:20],
        result_urls=[str(post.get("url", "")) for post in extracted_posts[:5] if post.get("url")],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="ok",
        error_type=None,
        confidence="medium",
        raw_payload={"posts": extracted_posts},
    )


def _status_evidence(record: HotRecord, fetched_at: str, status: str) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_weibo_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="weibo",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"微博讨论详情：{record.title}",
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


def extract_weibo_posts_from_text(page_text: str, max_items: int | None = None) -> list[dict[str, object]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    chunks: list[dict[str, object]] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if line.startswith("赞 ") or " 评论 " in line:
            content = "\n".join(current)
            chunks.append({"content": content, "comments_preview": [], "url": ""})
            current = []
    if current:
        chunks.append({"content": "\n".join(current), "comments_preview": [], "url": ""})
    return chunks[:max_items] if max_items is not None else chunks
