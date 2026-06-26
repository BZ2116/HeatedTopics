from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreatorProfile:
    creator_id: str
    role: str
    profile_type: str
    track_tags: list[str] = field(default_factory=list)
    custom_keywords: list[str] = field(default_factory=list)
    content_modes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "CreatorProfile":
        return cls(
            creator_id=str(row.get("creator_id", "")),
            role=str(row.get("role", "")),
            profile_type=str(row.get("profile_type", "")),
            track_tags=[str(item) for item in row.get("track_tags", [])],
            custom_keywords=[str(item) for item in row.get("custom_keywords", [])],
            content_modes=[str(item) for item in row.get("content_modes", [])],
        )

    def all_keywords(self) -> list[str]:
        values = [*self.track_tags, *self.custom_keywords]
        return _unique_nonempty(values)


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    source_role: str
    detail_level: str
    default_weight: int
    stability: str = "stable"
    enabled: bool = True


@dataclass(frozen=True)
class QueryBundle:
    category: str
    queries: list[str]


@dataclass(frozen=True)
class PlannedSource:
    source_id: str
    weight: int


@dataclass(frozen=True)
class SearchResult:
    result_id: str
    source_id: str
    source_role: str
    query: str
    keyword_category: str
    title: str
    url: str = ""
    domain: str = ""
    snippet: str = ""
    content_type: str = "unknown"
    published_at: str = ""
    fetched_at: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    fetch_status: str = "ok"
    error_type: str | None = None

    def has_usable_detail(self) -> bool:
        return bool(self.url and (self.snippet or self.raw_payload or self.content_type == "repo"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnrichedContent:
    result_id: str
    url: str
    title: str
    content: str
    author: str = ""
    published_at: str = ""
    content_quality: str = "low"
    extraction_method: str = "provider_snippet_or_reader"
    evidence_confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateTopic:
    topic_id: str
    title: str
    matched_keywords: list[str]
    keyword_categories: list[str]
    profile_match_score: int
    freshness: str
    detail_level: str
    risk_level: str
    source_hits: list[dict[str, Any]]
    summary: str
    open_questions: list[str] = field(default_factory=list)
    created_at: str = ""
    topic_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unique_nonempty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result