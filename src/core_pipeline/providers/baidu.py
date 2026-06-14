from src.core_pipeline.types import DetailEvidence, HotRecord


def collect_baidu_detail(
    record: HotRecord,
    fetched_at: str,
    search_results: list[dict[str, str]],
) -> DetailEvidence:
    usable_results = [row for row in search_results if row.get("title") or row.get("snippet")]
    status = "ok" if usable_results else "empty_content"
    content_parts = []
    result_urls = []
    for row in usable_results[:5]:
        title = row.get("title", "").strip()
        snippet = row.get("snippet", "").strip()
        url = row.get("url", "").strip()
        if url:
            result_urls.append(url)
        content_parts.append(f"{title}\n{snippet}".strip())
    content = "\n\n".join(part for part in content_parts if part)
    return DetailEvidence(
        evidence_id=f"evidence_baidu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="baidu",
        source_role="required",
        source_method="search_results",
        query=record.title,
        url=record.url,
        title=f"百度搜索详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=result_urls,
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium" if status == "ok" else "low",
        raw_payload={"search_results": search_results},
    )