import json
import urllib.parse
import urllib.request
from collections.abc import Callable

from src.search_discovery.types import EnrichedContent, SearchResult


PageReader = Callable[[str], str]


def _translate_to_chinese(text: str) -> str:
    if not text or len(text.strip()) < 10:
        return text
    if _has_chinese_signal(text):
        return text
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q={urllib.parse.quote(text[:2000])}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data and data[0]:
            return "".join(item[0] for item in data[0] if item[0])
    except Exception:
        pass
    return text


def _has_chinese_signal(value: str) -> bool:
    return any("一" <= char <= "鿿" for char in value)


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
        content = _translate_to_chinese(content)
        title = _translate_to_chinese(result.title)
        # Also translate snippet (used in cluster matching)
        snippet = _translate_to_chinese(result.snippet)
        quality = _content_quality(content, result.content_type)
        enriched.append(
            EnrichedContent(
                result_id=result.result_id,
                url=result.url,
                title=title,
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