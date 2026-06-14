from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HotRecord:
    id: str
    source: str
    platform: str
    route: str
    category: str
    title: str
    rank: int
    hot_value: str
    url: str
    mobile_url: str
    desc: str
    author: str
    cover: str
    timestamp: str
    captured_at: str
    raw_payload: dict[str, Any]
    fetch_status: str
    error_type: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DetailEvidence:
    evidence_id: str
    topic_key: str
    related_hot_record_ids: list[str]
    platform: str
    source_role: str
    source_method: str
    query: str
    url: str
    title: str
    content: str
    author: str
    published_at: str
    metrics: dict[str, Any]
    comments_preview: list[str]
    result_urls: list[str]
    raw_snapshot_path: str
    screenshot_path: str
    fetched_at: str
    fetch_status: str
    error_type: str | None
    confidence: str
    raw_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequiredDetailStatus:
    topic_key: str
    weibo: str
    xiaohongshu: str
    baidu: str
    missing_required_details: list[str]
    auxiliary_evidence_count: int
    detail_completeness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicCluster:
    topic_id: str
    canonical_title: str
    aliases: list[str]
    hot_record_ids: list[str]
    evidence_ids: list[str]
    platforms: list[str]
    required_detail_status: dict[str, str]
    detail_completeness: str
    cluster_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicBrief:
    topic_id: str
    canonical_title: str
    summary: str
    key_facts: list[str]
    platform_observations: dict[str, str]
    evidence_ids: list[str]
    missing_required_details: list[str]
    detail_completeness: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)