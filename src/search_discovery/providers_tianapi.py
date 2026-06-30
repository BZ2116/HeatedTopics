import os

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, make_error_row


class TianAPINewsProvider(BaseHTTPSearchProvider):
    source_id = "tianapi_news"
    rpm_limit = 60
    timeout_seconds = 10.0

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "TianAPINewsProvider | None":
        api_key = os.getenv("TIANAPI_KEY")
        if not api_key:
            return None
        return cls(api_key=api_key)

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "GET",
            "https://apis.tianapi.com/generalnews/index",
            params={"key": self._api_key, "word": query, "num": 10},
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        if int(body.get("code", 0)) != 200:
            return [make_error_row(source_id=self.source_id, query=query, category="", fetch_status="upstream_failed", error_type="upstream_code", fetched_at="")]
        rows: list[dict[str, object]] = []
        for item in body.get("newslist", []):
            url = item.get("url", "")
            if not url:
                continue
            rows.append(
                {
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("description", "") or item.get("digest", ""),
                    "content_type": "news",
                    "published_at": item.get("ctime", ""),
                    "raw_payload": item,
                }
            )
        return rows
