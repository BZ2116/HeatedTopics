import re
from typing import Any

from src.core_pipeline.types import HotRecord


SUPPORTED_WINDOWS = {
    "today": 1,
    "last_7_days": 7,
}

HOT_LIST_DECORATIONS = ("热", "爆", "新", "荐", "沸")


def collection_window_days(window: str) -> int:
    if window not in SUPPORTED_WINDOWS:
        supported = ", ".join(sorted(SUPPORTED_WINDOWS))
        raise ValueError(f"Unsupported collection window {window!r}; expected one of: {supported}")
    return SUPPORTED_WINDOWS[window]


def normalize_topic_key(title: str) -> str:
    normalized = str(title).strip().lower()
    normalized = re.sub(r"[!！?？#＃【】\[\]（）()：:，,。.\s]+", "", normalized)
    changed = True
    while changed:
        changed = False
        for suffix in HOT_LIST_DECORATIONS:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
    return normalized


def deduplicate_hot_records(records: list[HotRecord]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        topic_key = normalize_topic_key(record.title)
        if not topic_key:
            continue
        bucket = buckets.setdefault(
            topic_key,
            {
                "topic_key": topic_key,
                "canonical_title": record.title.strip(),
                "hot_record_ids": [],
                "platforms": set(),
                "records": [],
                "best_rank": record.rank,
            },
        )
        bucket["hot_record_ids"].append(record.id)
        bucket["platforms"].add(record.platform)
        bucket["records"].append(record)
        bucket["best_rank"] = min(bucket["best_rank"], record.rank)
        if record.rank == bucket["best_rank"]:
            bucket["canonical_title"] = record.title.strip()
    topics = []
    for bucket in buckets.values():
        topics.append(
            {
                "topic_key": bucket["topic_key"],
                "canonical_title": bucket["canonical_title"],
                "hot_record_ids": bucket["hot_record_ids"],
                "platforms": sorted(bucket["platforms"]),
                "best_rank": bucket["best_rank"],
                "records": bucket["records"],
            }
        )
    return sorted(topics, key=lambda topic: (topic["best_rank"], topic["canonical_title"]))