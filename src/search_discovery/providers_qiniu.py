import json
import os

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, make_error_row


class QiniuWebSearchProvider(BaseHTTPSearchProvider):
    source_id = "qiniu_web_search"
    rpm_limit = 60
    timeout_seconds = 10.0

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "QiniuWebSearchProvider | None":
        api_key = os.getenv("QINIU_WEB_SEARCH_API_KEY")
        if not api_key:
            return None
        return cls(api_key=api_key)

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://api.qiniu.com/ai/search/v1/web",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"query": query, "count": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        if int(body.get("code", 0)) != 0:
            return [make_error_row(source_id=self.source_id, query=query, category="", fetch_status="upstream_failed", error_type="upstream_code", fetched_at="")]
        values = body.get("data", {}).get("webPages", {}).get("value", [])
        rows: list[dict[str, object]] = []
        for item in values:
            url = item.get("url", "")
            if not url:
                continue
            rows.append(
                {
                    "title": item.get("name", ""),
                    "url": url,
                    "snippet": item.get("snippet", ""),
                    "content_type": "article",
                    "published_at": item.get("datePublished", ""),
                    "raw_payload": item,
                }
            )
        return rows
