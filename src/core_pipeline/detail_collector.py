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
        topic_platforms = {record.platform for record in records}
        if not topic_platforms.intersection(enabled_detail_platforms):
            for record in records:
                evidence_rows.append(dailyhot_metadata_evidence(record, fetched_at, related_ids, topic_key))
            continue
        cached_baidu = _read_detail_cache(cache_store, "baidu", topic_key)
        if cached_baidu is not None:
            evidence_rows.append(cached_baidu)
        else:
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
            _write_detail_cache(cache_store, baidu_evidence)
            if baidu_evidence.fetch_status != "ok" and representative.url and page_fetcher is not None:
                if representative.platform == "bilibili":
                    cached_bilibili = _read_detail_cache(cache_store, "bilibili", topic_key)
                    if cached_bilibili is not None:
                        evidence_rows.append(cached_bilibili)
                    else:
                        bilibili_evidence = video_metadata_evidence(representative, fetched_at, related_ids, topic_key)
                        evidence_rows.append(bilibili_evidence)
                        _write_detail_cache(cache_store, bilibili_evidence)
                else:
                    try:
                        evidence_rows.append(source_page_evidence(representative, fetched_at, related_ids, page_fetcher(representative.url), topic_key))
                    except Exception as exc:
                        evidence_rows.append(failed_source_page_evidence(representative, fetched_at, related_ids, type(exc).__name__, topic_key))
        weibo_status = session_status.get("weibo", "login_required")
        cached_weibo = _read_detail_cache(cache_store, "weibo", topic_key)
        if cached_weibo is not None:
            evidence_rows.append(cached_weibo)
        else:
            weibo_posts = _fetch_social_rows("weibo", representative.title, weibo_status, social_detail_fetcher)
            weibo_evidence = collect_weibo_detail(representative, fetched_at, weibo_status, weibo_posts)
            object.__setattr__(weibo_evidence, "topic_key", topic_key)
            evidence_rows.append(weibo_evidence)
            _write_detail_cache(cache_store, weibo_evidence)
        xiaohongshu_status = session_status.get("xiaohongshu", "login_required")
        cached_xiaohongshu = _read_detail_cache(cache_store, "xiaohongshu", topic_key)
        if cached_xiaohongshu is not None:
            evidence_rows.append(cached_xiaohongshu)
        else:
            xiaohongshu_notes = _fetch_social_rows("xiaohongshu", representative.title, xiaohongshu_status, social_detail_fetcher)
            xiaohongshu_evidence = collect_xiaohongshu_detail(representative, fetched_at, xiaohongshu_status, xiaohongshu_notes)
            object.__setattr__(xiaohongshu_evidence, "topic_key", topic_key)
            evidence_rows.append(xiaohongshu_evidence)
            _write_detail_cache(cache_store, xiaohongshu_evidence)
    return evidence_rows


def _fetch_social_rows(
    platform: str,
    query: str,
    session_status: str,
    social_detail_fetcher: SocialDetailFetcher | None,
) -> list[dict[str, object]]:
    if session_status != "ok" or social_detail_fetcher is None:
        return []
    return social_detail_fetcher(platform, query)
