from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from src.search_discovery.types import SearchResult


class SearchProvider(Protocol):
    source_id: str

    def search_rows(self, query: str, **kwargs) -> list[dict[str, object]]:
        raise NotImplementedError


@dataclass
class MockProvider:
    source_id: str
    rows: list[dict[str, object]]

    def search_rows(self, query: str, **kwargs) -> list[dict[str, object]]:
        return self.rows


class SearchProviderRegistry:
    def __init__(self, providers: list[SearchProvider]) -> None:
        self._providers = {provider.source_id: provider for provider in providers}

    @property
    def providers(self) -> dict[str, SearchProvider]:
        return self._providers

    def search(
        self,
        source_id: str,
        source_role: str,
        query: str,
        keyword_category: str,
        fetched_at: str,
        index: int = 0,
    ) -> list[SearchResult]:
        provider = self._providers.get(source_id)
        if provider is None:
            return []
        rows = provider.search_rows(
            query, keyword_category=keyword_category, fetched_at=fetched_at, index=index,
        )
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
            result_id=str(row.get("result_id", f"{source_id}_{index:03d}")),
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
            fetch_status=str(row.get("fetch_status", "ok")),
            error_type=row.get("error_type"),
            route_weight=int(row.get("route_weight", 0) or 0),
            route_reason=str(row.get("route_reason", "")),
            matched_keywords=[str(item) for item in row.get("matched_keywords", [])],
        )
        if result.fetch_status == "ok" and not result.has_usable_detail():
            continue
        results.append(result)
    return results


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc
