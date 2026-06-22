import html
import re
from collections.abc import Callable
from typing import Any

from src.core_pipeline.providers.baidu import collect_baidu_detail, detail_queries_for_title
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.types import DetailEvidence, HotRecord


SearchProvider = Callable[[str], list[dict[str, str]]]
PageFetcher = Callable[[str], str]


def html_to_text(page_html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", page_html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def source_page_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    page_text: str,
    topic_key: str | None = None,
) -> DetailEvidence:
    content = html_to_text(page_text)
    status = "ok" if content else "empty_content"
    return DetailEvidence(
        evidence_id=f"evidence_source_{record.id}",
        topic_key=topic_key or record.title,
        related_hot_record_ids=related_hot_record_ids,
        platform=record.platform,
        source_role="required",
        source_method="source_url",
        query=record.title,
        url=record.url,
        title=f"{record.platform} 原始页面详情：{record.title}",
        content=content,
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[record.url] if record.url else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium" if status == "ok" else "low",
        raw_payload={"source_url": record.url},
    )


def failed_source_page_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    error_type: str,
    topic_key: str | None = None,
) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_source_{record.id}",
        topic_key=topic_key or record.title,
        related_hot_record_ids=related_hot_record_ids,
        platform=record.platform,
        source_role="required",
        source_method="source_url",
        query=record.title,
        url=record.url,
        title=f"{record.platform} 原始页面详情：{record.title}",
        content="",
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[record.url] if record.url else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="failed",
        error_type=error_type,
        confidence="low",
        raw_payload={"source_url": record.url},
    )


def collect_topic_details(
    topics: list[dict[str, Any]],
    fetched_at: str,
    search_provider: SearchProvider,
    session_status: dict[str, str],
    page_fetcher: PageFetcher | None = None,
) -> list[DetailEvidence]:
    evidence_rows: list[DetailEvidence] = []
    for topic in topics:
        records = [record for record in topic.get("records", []) if isinstance(record, HotRecord)]
        if not records:
            continue
        representative = records[0]
        topic_key = str(topic.get("topic_key") or representative.title)
        related_ids = list(topic.get("hot_record_ids") or [representative.id])
        query_results: list[dict[str, str]] = []
        used_query = representative.title
        for query in detail_queries_for_title(representative.title):
            results = search_provider(query)
            if results:
                query_results = results
                used_query = query
                break
        baidu_evidence = collect_baidu_detail(representative, fetched_at, query_results)
        object.__setattr__(baidu_evidence, "topic_key", topic_key)
        object.__setattr__(baidu_evidence, "related_hot_record_ids", related_ids)
        evidence_rows.append(baidu_evidence)
        if baidu_evidence.fetch_status != "ok" and representative.url and page_fetcher is not None:
            try:
                evidence_rows.append(source_page_evidence(representative, fetched_at, related_ids, page_fetcher(representative.url), topic_key))
            except Exception as exc:
                evidence_rows.append(failed_source_page_evidence(representative, fetched_at, related_ids, type(exc).__name__, topic_key))
        weibo_evidence = collect_weibo_detail(
            representative,
            fetched_at,
            session_status.get("weibo", "login_required"),
            [],
        )
        object.__setattr__(weibo_evidence, "topic_key", topic_key)
        evidence_rows.append(weibo_evidence)
        xiaohongshu_evidence = collect_xiaohongshu_detail(
            representative,
            fetched_at,
            session_status.get("xiaohongshu", "login_required"),
            [],
        )
        object.__setattr__(xiaohongshu_evidence, "topic_key", topic_key)
        evidence_rows.append(xiaohongshu_evidence)
    return evidence_rows
