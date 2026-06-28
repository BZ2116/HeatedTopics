import json
import os
from urllib.parse import urlparse

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, ProviderError


class BailianWebSearchProvider(BaseHTTPSearchProvider):
    source_id = "juejin_content"  # keep existing ID; this provider replaces the slot
    rpm_limit = 60
    timeout_seconds = 10.0

    ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/apps/web_search"

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "BailianWebSearchProvider | None":
        key = os.getenv("BAILIAN_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            self.ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"query": query, "top_k": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        # DashScope success envelopes may not include a top-level `code`,
        # but failure envelopes do. Validate defensively when present.
        code = body.get("code")
        if code is not None and code != 0:
            raise ProviderError("upstream_failed", f"bailian_code_{code}")
        results = body.get("output", {}).get("search_results", [])
        rows: list[dict[str, object]] = []
        for item in results:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("title", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("snippet", "") or "",
                "content_type": item.get("content_type", "article"),
                "published_at": item.get("published_at", "") or "",
                "metrics": {},
            })
        return rows