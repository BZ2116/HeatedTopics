from collections.abc import Callable

from src.search_discovery.types import EnrichedContent, SearchResult


PageReader = Callable[[str], str]


def enrich_results(results: list[SearchResult], page_reader: PageReader | None = None) -> list[EnrichedContent]:
    enriched = []
    for result in results:
        content = ""
        method = "provider_snippet_or_reader"
        if page_reader is not None and result.url:
            try:
                content = page_reader(result.url).strip()
                method = "reader"
            except Exception:
                content = ""
        if not content:
            content = result.snippet.strip()
        quality = _content_quality(content, result.content_type)
        enriched.append(
            EnrichedContent(
                result_id=result.result_id,
                url=result.url,
                title=result.title,
                content=content,
                author=str(result.raw_payload.get("author", "")),
                published_at=result.published_at,
                content_quality=quality,
                extraction_method=method,
                evidence_confidence="high" if quality == "high" else "medium" if quality == "medium" else "low",
            )
        )
    return enriched


def _content_quality(content: str, content_type: str) -> str:
    if content_type == "repo" and content:
        return "high"
    if len(content) >= 300:
        return "high"
    if content:
        return "medium"
    return "low"