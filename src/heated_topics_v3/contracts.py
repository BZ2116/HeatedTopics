"""Immutable data contracts shared by the collection and recommendation workflow."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


HeatLevel = Literal[1, 2, 3]
FactStatus = Literal["verified", "unverified", "disputed", "debunked"]
ContentStatus = Literal["full_text", "summary", "title_only"]
GenerationStatus = Literal["existing", "generated", "no_result", "not_ready", "failed"]
CollectionStatus = Literal["success", "partial", "failed"]
EvidenceSource = Literal["official_hot_board", "public_engagement"]
QualificationStatus = Literal["accepted", "rejected"]


_SAFE_USER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def validate_user_id(value: str) -> str:
    """Validate the single safe path segment used for persisted user results."""
    if not isinstance(value, str) or _SAFE_USER_ID.fullmatch(value) is None:
        raise ValueError("user_id must be 1-64 ASCII letters, digits, '_' or '-'")
    return value


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    primary_track: str
    secondary_track: str
    persona: str
    primary_keyword: str
    updated_at: str

    def __post_init__(self) -> None:
        validate_user_id(self.user_id)


@dataclass(frozen=True)
class HeatMetrics:
    value: int | float | None
    label: str
    metric_name: str
    metrics: Mapping[str, int | float] = field(default_factory=dict)


@dataclass(frozen=True)
class HotItem:
    item_id: str
    platform: str
    title: str
    url: str
    rank: int | None
    heat: HeatMetrics
    summary: str
    publication_time: str | None
    collected_at: str
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ItemDetail:
    item_id: str
    content: str
    content_status: ContentStatus
    publication_time: str | None
    collected_at: str
    source_url: str
    fetch_status: str


@dataclass(frozen=True)
class HeatEvidence:
    source_kind: EvidenceSource
    platform_rank: int | None
    native_hot_value: float | None
    metrics: Mapping[str, float] = field(default_factory=dict)
    threshold_metrics: Mapping[str, float] = field(default_factory=dict)
    qualified_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentValidation:
    status: QualificationStatus
    parser: str
    character_count: int
    paragraph_count: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualifiedArticle:
    hot_item: HotItem
    detail: ItemDetail
    heat_evidence: HeatEvidence
    content_validation: ContentValidation
    platform_heat_score: float

    def __post_init__(self) -> None:
        if self.detail.content_status != "full_text":
            raise ValueError("qualified article requires full_text")
        if self.content_validation.status != "accepted":
            raise ValueError("qualified article requires accepted content")
        if not self.heat_evidence.qualified_by:
            raise ValueError("qualified article requires heat evidence")


@dataclass(frozen=True)
class PlatformCollectionStatus:
    platform: str
    status: CollectionStatus
    collected_at: str
    item_count: int
    error: str | None = None


@dataclass(frozen=True)
class DailySnapshot:
    business_date: str
    collected_at: str
    items_by_platform: Mapping[str, tuple[HotItem, ...]]
    platform_statuses: tuple[PlatformCollectionStatus, ...] = ()


@dataclass(frozen=True)
class RecommendationItem:
    hot_item_id: str
    platform: str
    title: str
    heat_level: HeatLevel
    fact_status: FactStatus
    publication_time: str | None
    collected_at: str
    detail: str
    content_status: ContentStatus
    is_personalized: bool
    evidence: Mapping[str, Any] = field(default_factory=dict)
    source_url: str = ""


@dataclass(frozen=True)
class RecommendationBundle:
    status: GenerationStatus
    user_id: str
    business_date: str
    generated_at: str
    recommendations: tuple[RecommendationItem, ...]
    potential_topics: tuple[RecommendationItem, ...]
    general_fallback: tuple[RecommendationItem, ...]
    query_metadata: Mapping[str, Any] = field(default_factory=dict)
