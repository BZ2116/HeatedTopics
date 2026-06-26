from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from src.search_discovery.types import SearchResult


class SearchProvider(Protocol):
    source_id: str

    def search_rows(self, query: str) -> list[dict[str, object]]:
        raise NotImplementedError


@dataclass
class MockProvider:
    source_id: str
    rows: list[dict[str, object]]

    def search_rows(self, query: str) -> list[dict[str, object]]:
        return self.rows


class SearchProviderRegistry:
    def __init__(self, providers: list[SearchProvider]) -> None:
        self._providers = {provider.source_id: provider for provider in providers}

    def search(
        self,
        source_id: str,
        source_role: str,
        query: str,
        keyword_category: str,
        fetched_at: str,
    ) -> list[SearchResult]:
        provider = self._providers.get(source_id)
        if provider is None:
            return []
        rows = provider.search_rows(query)
        return normalize_provider_rows(rows, source_id, source_role, query, keyword_category, fetched_at)


def normalize_provider_rows(
    rows: list[dict[str, object]],
    source_id: str,
    source_role: str,
    query: str,
    keyword_category: str,
    fetched_at: str,
) -> list[SearchResult]:
    results = []
    for index, row in enumerate(rows, start=1):
        title = str(row.get("title", "")).strip()
        url = str(row.get("url", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        content_type = str(row.get("content_type", "unknown")).strip() or "unknown"
        result = SearchResult(
            result_id=f"{source_id}_{index:03d}",
            source_id=source_id,
            source_role=source_role,
            query=query,
            keyword_category=keyword_category,
            title=title,
            url=url,
            domain=_domain(url),
            snippet=snippet,
            content_type=content_type,
            published_at=str(row.get("published_at", "")),
            fetched_at=fetched_at,
            metrics=row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {},
            raw_payload=dict(row),
        )
        if result.has_usable_detail():
            results.append(result)
    return results


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc