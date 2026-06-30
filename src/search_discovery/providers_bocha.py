import json
import os
from urllib.parse import urlparse

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, ProviderError


class BochaSearchProvider(BaseHTTPSearchProvider):
    source_id = "news_api_cn"  # keep existing ID for config compatibility
    rpm_limit = 60
    timeout_seconds = 10.0

    ENDPOINT = "https://api.bochaai.com/v1/web-search"

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "BochaSearchProvider | None":
        key = os.getenv("BOCHA_API_KEY")
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
            # Bocha returns a `summary` field when True, in addition to snippet.
            content=json.dumps({"query": query, "summary": True, "count": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        code = body.get("code", 0)
        if code != 0:
            raise ProviderError("upstream_failed", f"bocha_code_{code}")
        webpages = body.get("data", {}).get("webPages", {}).get("value", [])
        rows: list[dict[str, object]] = []
        for item in webpages:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("name", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("snippet", "") or "",
                "content_type": "news",
                "published_at": item.get("datePublished", "") or "",
                "metrics": {},
            })
        return rows