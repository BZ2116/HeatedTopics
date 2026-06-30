import json
import os

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, make_error_row


class TavilySearchProvider(BaseHTTPSearchProvider):
    source_id = "tavily_search"
    rpm_limit = 60
    timeout_seconds = 15.0

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "TavilySearchProvider | None":
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return None
        return cls(api_key=api_key)

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(
                {
                    "query": query,
                    "topic": "news",
                    "country": "china",
                    "search_depth": "advanced",
                    "max_results": 10,
                    "include_answer": False,
                    "include_raw_content": True,
                }
            ),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        if "error" in body:
            return [
                make_error_row(
                    source_id=self.source_id,
                    query=query,
                    category="",
                    fetch_status="upstream_failed",
                    error_type="upstream_error",
                    fetched_at="",
                )
            ]
        rows: list[dict[str, object]] = []
        for item in body.get("results", []):
            url = item.get("url", "")
            if not url:
                continue
            rows.append(
                {
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("content", ""),
                    "content_type": "news" if item.get("published_date") else "article",
                    "published_at": item.get("published_date", ""),
                    "metrics": {"score": item.get("score", 0)},
                    "raw_payload": item,
                }
            )
        return rows
