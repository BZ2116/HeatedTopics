from collections.abc import Callable
from typing import Any

from src.core_pipeline.providers.baidu import collect_baidu_detail, detail_queries_for_title
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.types import DetailEvidence, HotRecord


SearchProvider = Callable[[str], list[dict[str, str]]]


def collect_topic_details(
    topics: list[dict[str, Any]],
    fetched_at: str,
    search_provider: SearchProvider,
    session_status: dict[str, str],
) -> list[DetailEvidence]:
    evidence_rows: list[DetailEvidence] = []
    for topic in topics:
        records = [record for record in topic.get("records", []) if isinstance(record, HotRecord)]
        if not records:
            continue
        representative = records[0]
        query_results: list[dict[str, str]] = []
        used_query = representative.title
        for query in detail_queries_for_title(representative.title):
            results = search_provider(query)
            if results:
                query_results = results
                used_query = query
                break
        baidu_evidence = collect_baidu_detail(representative, fetched_at, query_results)
        object.__setattr__(baidu_evidence, "related_hot_record_ids", list(topic.get("hot_record_ids") or [representative.id]))
        evidence_rows.append(baidu_evidence)
        evidence_rows.append(
            collect_weibo_detail(
                representative,
                fetched_at,
                session_status.get("weibo", "login_required"),
                [],
            )
        )
        evidence_rows.append(
            collect_xiaohongshu_detail(
                representative,
                fetched_at,
                session_status.get("xiaohongshu", "login_required"),
                [],
            )
        )
    return evidence_rows
