from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    display_name: str
    domains: tuple[str, ...]
    audience: tuple[str, ...]
    content_modes: tuple[str, ...]
    preferred_platforms: tuple[str, ...]
    core_keywords: tuple[str, ...]
    entity_keywords: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopicQuery:
    query_id: str
    profile_id: str
    query: str
    intent: str
    target_platforms: tuple[str, ...]
    keywords: tuple[str, ...]
    usage: str
    priority: int


@dataclass(frozen=True)
class HeatMetrics:
    value: int | None
    label: str
    metric_name: str
    metrics: dict[str, int | float] = field(default_factory=dict)


@dataclass(frozen=True)
class HotItem:
    item_id: str
    platform: str
    item_type: str
    title: str
    url: str
    rank: int | None
    heat: HeatMetrics
    summary: str
    category: str
    matched_query_ids: tuple[str, ...]
    fetched_at: str
    fetch_status: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ItemDetail:
    item_id: str
    platform: str
    url: str
    title: str
    author: str
    content: str
    published_at: str
    tags: tuple[str, ...]
    extraction_method: str
    fetch_status: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class TopicCluster:
    topic_id: str
    canonical_title: str
    source_item_ids: tuple[str, ...]
    platforms: tuple[str, ...]
    matched_profile_ids: tuple[str, ...]
    summary: str
    is_usable: bool
    confidence: str


@dataclass(frozen=True)
class ReportBundle:
    generated_at: str
    profile_id: str
    hot_items: tuple[HotItem, ...]
    topic_clusters: tuple[TopicCluster, ...]
    report_markdown: str


@dataclass(frozen=True)
class MatchResult:
    item: HotItem
    match_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    relevance_score: int
    is_relevant: bool


@dataclass(frozen=True)
class PersonaPersonal:
    role: str
    subject: str
    scenarios: tuple[str, ...]
    value: str


@dataclass(frozen=True)
class PersonaProfile:
    user_id: str
    level1: str
    level2: str
    personal: PersonaPersonal
    core_keywords: tuple[str, ...]
    persona_signature: str


@dataclass(frozen=True)
class ExtractedKeyword:
    keyword: str
    match_expectation: str  # "热榜" | "长尾" | "兜底"


@dataclass(frozen=True)
class HotBoardSnapshot:
    date: str  # "YYYY-MM-DD" (UTC+8)
    fetched_at: str
    items: tuple[HotItem, ...]
