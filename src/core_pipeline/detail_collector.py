import html
import re
from collections.abc import Callable
from typing import Any

from src.core_pipeline.cache_store import CacheStore
from src.core_pipeline.providers.baidu import collect_baidu_detail, detail_queries_for_title
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail, collect_xiaohongshu_placeholder_detail
from src.core_pipeline.source_registry import DETAIL_ENABLED_PLATFORMS
from src.core_pipeline.types import DetailEvidence, HotRecord


SearchProvider = Callable[[str], list[dict[str, str]]]
PageFetcher = Callable[[str], str]
SocialDetailFetcher = Callable[[str, str], list[dict[str, object]] | dict[str, object]]
ProgressCallback = Callable[[int, int, str], None]


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


def failed_social_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    platform: str,
    query: str,
    error_type: str,
    topic_key: str | None = None,
) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_{platform}_{record.id}",
        topic_key=topic_key or record.title,
        related_hot_record_ids=related_hot_record_ids,
        platform=platform,
        source_role="required",
        source_method="browser_session",
        query=query,
        url=record.url,
        title=f"{platform} browser detail failed: {query}",
        content="",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=[],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="failed",
        error_type=error_type,
        confidence="low",
        raw_payload={"platform": platform, "query": query, "error_type": error_type, "record": record.to_dict()},
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
    supplemental_social_platforms: tuple[str, ...] = (),
    progress: ProgressCallback | None = None,
) -> list[DetailEvidence]:
    evidence_rows: list[DetailEvidence] = []
    total = len(topics)
    for idx, topic in enumerate(topics, start=1):
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
                evidence = _collect_social_record_detail(record, topic_key, related_ids, fetched_at, "weibo", status, social_detail_fetcher)
            elif record.platform == "xiaohongshu":
                evidence = collect_xiaohongshu_placeholder_detail(record, fetched_at)
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
        present_platforms = {record.platform for record in records}
        for platform in supplemental_social_platforms:
            if platform in present_platforms or platform != "weibo":
                continue
            if platform not in enabled_detail_platforms or session_status.get(platform) != "ok":
                continue
            cached = _read_detail_cache(cache_store, platform, topic_key)
            if cached is not None:
                evidence_rows.append(cached)
                continue
            synthetic_record = _synthetic_social_record(platform, representative, topic_key)
            evidence = _collect_social_record_detail(
                synthetic_record,
                topic_key,
                related_ids,
                fetched_at,
                platform,
                "ok",
                social_detail_fetcher,
            )
            evidence_rows.append(evidence)
            _write_detail_cache(cache_store, evidence)
        if progress is not None:
            progress(idx, total, f"采集详情证据：{topic_key}")
    return evidence_rows


def _synthetic_social_record(platform: str, seed_record: HotRecord, topic_key: str) -> HotRecord:
    return HotRecord(
        id=f"hot_{platform}_supplemental_{topic_key}",
        source="browser_search",
        platform=platform,
        route=platform,
        category=seed_record.category,
        title=seed_record.title,
        rank=seed_record.rank,
        hot_value=seed_record.hot_value,
        url="",
        mobile_url="",
        desc=seed_record.desc,
        author="",
        cover="",
        timestamp="",
        captured_at=seed_record.captured_at,
        raw_payload={"seed_record": seed_record.to_dict(), "supplemental_platform": platform},
        fetch_status="ok",
        error_type=None,
    )


def _collect_baidu_record_detail(
    record: HotRecord,
    topic_key: str,
    related_ids: list[str],
    fetched_at: str,
    search_provider: SearchProvider,
    page_fetcher: PageFetcher | None,
) -> DetailEvidence:
    query_results: list[dict[str, str]] = []
    query_attempts: list[dict[str, object]] = []
    for query in detail_queries_for_title(record.title):
        results = search_provider(query)
        query_attempts.append({"query": query, "result_count": len(results), "results": results})
        if results:
            query_results = results
            break
    content_pages = _collect_baidu_content_pages(query_results, page_fetcher)
    evidence = collect_baidu_detail(record, fetched_at, query_results, content_pages)
    object.__setattr__(evidence, "topic_key", topic_key)
    object.__setattr__(evidence, "related_hot_record_ids", related_ids)
    object.__setattr__(evidence, "raw_payload", {**evidence.raw_payload, "query_attempts": query_attempts})
    if evidence.fetch_status == "ok" or not record.url or page_fetcher is None:
        return evidence
    try:
        return source_page_evidence(record, fetched_at, related_ids, page_fetcher(record.url), topic_key)
    except Exception as exc:
        return failed_source_page_evidence(record, fetched_at, related_ids, type(exc).__name__, topic_key)


def _collect_baidu_content_pages(
    search_results: list[dict[str, str]],
    page_fetcher: PageFetcher | None,
    max_pages: int = 3,
) -> list[dict[str, object]]:
    if page_fetcher is None:
        return []
    pages: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for index, result in enumerate(search_results, start=1):
        if len(pages) >= max_pages:
            break
        url = str(result.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            content = html_to_text(page_fetcher(url))
        except Exception as exc:
            pages.append(
                {
                    "index": index,
                    "url": url,
                    "title": str(result.get("title", "")),
                    "content": "",
                    "raw_text": "",
                    "fetch_status": "failed",
                    "error_type": type(exc).__name__,
                }
            )
            continue
        if not content:
            continue
        pages.append(
            {
                "index": index,
                "url": url,
                "title": str(result.get("title", "")),
                "content": content,
                "raw_text": content,
                "fetch_status": "ok",
                "error_type": "",
            }
        )
    return pages


def _collect_social_record_detail(
    record: HotRecord,
    topic_key: str,
    related_ids: list[str],
    fetched_at: str,
    platform: str,
    status: str,
    social_detail_fetcher: SocialDetailFetcher | None,
) -> DetailEvidence:
    try:
        rows, browser_raw = _fetch_social_rows(platform, record.title, status, social_detail_fetcher)
    except Exception as exc:
        error_type = str(exc) or type(exc).__name__
        return failed_social_evidence(record, fetched_at, related_ids, platform, record.title, error_type, topic_key)
    if platform == "weibo":
        evidence = collect_weibo_detail(record, fetched_at, status, rows)
    else:
        evidence = collect_xiaohongshu_detail(record, fetched_at, status, rows)
    object.__setattr__(evidence, "topic_key", topic_key)
    object.__setattr__(evidence, "related_hot_record_ids", related_ids)
    if browser_raw:
        object.__setattr__(evidence, "raw_payload", {**evidence.raw_payload, "browser_raw": browser_raw})
    return evidence


def _fetch_social_rows(
    platform: str,
    query: str,
    session_status: str,
    social_detail_fetcher: SocialDetailFetcher | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if session_status != "ok" or social_detail_fetcher is None:
        return [], {}
    result = social_detail_fetcher(platform, query)
    if isinstance(result, dict):
        raw = result.get("raw")
        rows = result.get("rows")
        if rows is None:
            rows = result.get("posts") if platform == "weibo" else result.get("notes")
        if not isinstance(rows, list):
            rows = []
        return [row for row in rows if isinstance(row, dict)], raw if isinstance(raw, dict) else result
    return [row for row in result if isinstance(row, dict)], {"rows": result}
