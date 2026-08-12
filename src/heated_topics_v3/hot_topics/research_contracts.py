"""Contracts for external research and citation-backed evidence."""

from dataclasses import dataclass
from typing import Literal


EvidenceStatus = Literal["verified_article", "search_cited", "hot_item_only", "uncorroborated"]


@dataclass(frozen=True)
class SearchTask:
    topic_id: str
    query: str
    purpose: str


@dataclass(frozen=True)
class SearchEvidence:
    topic_id: str
    query: str
    title: str
    url: str
    source: str
    published_at: str | None
    snippet: str
    retrieved_at: str
    provider: str
    evidence_status: EvidenceStatus

    def __post_init__(self) -> None:
        for field_name in ("topic_id", "query", "title", "url", "provider"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.evidence_status == "search_cited" and not self.snippet.strip():
            raise ValueError("search_cited evidence requires a snippet")

