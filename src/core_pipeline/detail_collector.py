import html
import re
from collections.abc import Callable
from typing import Any

from src.core_pipeline.cache_store import CacheStore
from src.core_pipeline.providers.baidu import collect_baidu_detail, detail_queries_for_title
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.source_registry import DETAIL_ENABLED_PLATFORMS
from src.core_pipeline.types import DetailEvidence, HotRecord


SearchProvider = Callable[[str], list[dict[str, str]]]
PageFetcher = Callable[[str], str]
SocialDetailFetcher = Callable[[str, str], list[dict[str, object]]]


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
        raw_payload={"source_url": record.url, "raw_page_text": page_text, "record": record.to_dict()},
    )


def video_metadata_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    topic_key: str | None = None,
) -> DetailEvidence:
    link = record.url or record.mobile_url
    content_parts = [
        f"视频标题：{record.title}",
        f"视频简介：{record.desc}" if record.desc else "",
        f"视频链接：{link}" if link else "",
    ]
    content = "\n".join(part for part in content_parts if part).strip()
    status = "ok" if content else "empty_content"
    return DetailEvidence(
        evidence_id=f"evidence_video_{record.id}",
        topic_key=topic_key or record.title,
        related_hot_record_ids=related_hot_record_ids,
        platform=record.platform,
        source_role="required",
        source_method="video_metadata",
        query=record.title,
        url=link,
        title=f"{record.platform} 视频详情：{record.title}",
        content=content,
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[link] if link else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium" if status == "ok" else "low",
        raw_payload={"record": record.to_dict()},
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


def dailyhot_metadata_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    topic_key: str | None = None,
) -> DetailEvidence:
    content = "\n".join(
        part
        for part in [
            f"Title: {record.title}",
            f"Description: {record.desc}" if record.desc else "",
            f"URL: {record.url or record.mobile_url}" if record.url or record.mobile_url else "",
        ]
        if part
    )
    return DetailEvidence(
        evidence_id=f"evidence_metadata_{record.id}",
        topic_key=topic_key or record.title,
        related_hot_record_ids=related_hot_record_ids,
        platform=record.platform,
        source_role="auxiliary",
        source_method="dailyhot_metadata",
        query=record.title,
        url=record.url or record.mobile_url,
        title=f"{record.platform} DailyHot metadata: {record.title}",
        content=content,
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[record.url or record.mobile_url] if record.url or record.mobile_url else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="ok" if content else "empty_content",
        error_type=None if content else "empty_content",
        confidence="low",
        raw_payload={"record": record.to_dict()},
    )


def juejin_metadata_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    topic_key: str | None = None,
) -> DetailEvidence:
    evidence = dailyhot_metadata_evidence(record, fetched_at, related_hot_record_ids, topic_key)
    object.__setattr__(evidence, "evidence_id", f"evidence_juejin_{record.id}")
    object.__setattr__(evidence, "source_role", "required")
    object.__setattr__(evidence, "source_method", "juejin_metadata")
    object.__setattr__(evidence, "title", f"juejin article metadata: {record.title}")
    object.__setattr__(evidence, "confidence", "medium")
    return evidence


def _detail_cache_key(platform: str, topic_key: str) -> str:
    return f"detail:{platform}:{topic_key}"


def _read_detail_cache(cache_store: CacheStore | None, platform: str, topic_key: str) -> DetailEvidence | None:
    if cache_store is None:
        return None
    row = cache_store.read(_detail_cache_key(platform, topic_key))
    if row is None:
        return None
    return DetailEvidence(**row)


def _write_detail_cache(cache_store: CacheStore | None, evidence: DetailEvidence) -> None:
    if cache_store is None:
        return
    if evidence.fetch_status != "ok":
        return
    cache_store.write(_detail_cache_key(evidence.platform, evidence.topic_key), evidence.to_dict(), fetched_at=evidence.fetched_at)


def collect_topic_details(
    topics: list[dict[str, Any]],
    fetched_at: str,
    search_provider: SearchProvider,
    session_status: dict[str, str],
    page_fetcher: PageFetcher | None = None,
    social_detail_fetcher: SocialDetailFetcher | None = None,
    enabled_detail_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS,
    cache_store: CacheStore | None = None,
) -> list[DetailEvidence]:
    evidence_rows: list[DetailEvidence] = []
    for topic in topics:
        records = [record for record in topic.get("records", []) if isinstance(record, HotRecord)]
        if not records:
            continue
        representative = records[0]
        topic_key = str(topic.get("topic_key") or representative.title)
        related_ids = list(topic.get("hot_record_ids") or [representative.id])
        for record in records:
            if record.platform not in enabled_detail_platforms:
                evidence = dailyhot_metadata_evidence(record, fetched_at, related_ids, topic_key)
                evidence_rows.append(evidence)
                _write_detail_cache(cache_store, evidence)
                continue

            cached = _read_detail_cache(cache_store, record.platform, topic_key)
            if cached is not None:
                evidence_rows.append(cached)
                continue

            if record.platform == "baidu":
                evidence = _collect_baidu_record_detail(record, topic_key, related_ids, fetched_at, search_provider, page_fetcher)
            elif record.platform == "weibo":
                status = session_status.get("weibo", "login_required")
                posts = _fetch_social_rows("weibo", record.title, status, social_detail_fetcher)
                evidence = collect_weibo_detail(record, fetched_at, status, posts)
                object.__setattr__(evidence, "topic_key", topic_key)
                object.__setattr__(evidence, "related_hot_record_ids", related_ids)
            elif record.platform == "xiaohongshu":
                status = session_status.get("xiaohongshu", "login_required")
                notes = _fetch_social_rows("xiaohongshu", record.title, status, social_detail_fetcher)
                evidence = collect_xiaohongshu_detail(record, fetched_at, status, notes)
                object.__setattr__(evidence, "topic_key", topic_key)
                object.__setattr__(evidence, "related_hot_record_ids", related_ids)
            elif record.platform == "bilibili":
                evidence = video_metadata_evidence(record, fetched_at, related_ids, topic_key)
            elif record.platform == "juejin":
                evidence = juejin_metadata_evidence(record, fetched_at, related_ids, topic_key)
            else:
                evidence = dailyhot_metadata_evidence(record, fetched_at, related_ids, topic_key)
            evidence_rows.append(evidence)
            _write_detail_cache(cache_store, evidence)
    return evidence_rows


def _collect_baidu_record_detail(
    record: HotRecord,
    topic_key: str,
    related_ids: list[str],
    fetched_at: str,
    search_provider: SearchProvider,
    page_fetcher: PageFetcher | None,
) -> DetailEvidence:
    query_results: list[dict[str, str]] = []
    for query in detail_queries_for_title(record.title):
        results = search_provider(query)
        if results:
            query_results = results
            break
    evidence = collect_baidu_detail(record, fetched_at, query_results)
    object.__setattr__(evidence, "topic_key", topic_key)
    object.__setattr__(evidence, "related_hot_record_ids", related_ids)
    if evidence.fetch_status == "ok" or not record.url or page_fetcher is None:
        return evidence
    try:
        return source_page_evidence(record, fetched_at, related_ids, page_fetcher(record.url), topic_key)
    except Exception as exc:
        return failed_source_page_evidence(record, fetched_at, related_ids, type(exc).__name__, topic_key)


def _fetch_social_rows(
    platform: str,
    query: str,
    session_status: str,
    social_detail_fetcher: SocialDetailFetcher | None,
) -> list[dict[str, object]]:
    if session_status != "ok" or social_detail_fetcher is None:
        return []
    return social_detail_fetcher(platform, query)
