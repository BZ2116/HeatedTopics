import json
import os
import time
from urllib.parse import urlparse

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, ProviderError


class QianfanSearchProvider(BaseHTTPSearchProvider):
    source_id = "baidu_qianfan_search"
    rpm_limit = 60
    timeout_seconds = 10.0

    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    SEARCH_URL = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/plugin/search"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        transport: httpx.BaseTransport | None = None,
        clock=time.time,
    ):
        super().__init__(transport=transport)
        self._api_key = api_key
        self._secret_key = secret_key
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._clock = clock

    @classmethod
    def from_env(cls) -> "QianfanSearchProvider | None":
        api_key = os.getenv("QIANFAN_API_KEY")
        secret_key = os.getenv("QIANFAN_SECRET_KEY")
        if not api_key or not secret_key:
            return None
        return cls(api_key=api_key, secret_key=secret_key)

    def _ensure_token(self) -> None:
        if self._access_token and self._clock() < self._token_expires_at:
            return
        request = httpx.Request(
            "GET",
            self.TOKEN_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": self._secret_key,
            },
        )
        response = self._client.send(request)
        if response.status_code != 200:
            raise ProviderError("auth_failed", "token_exchange_failed")
        body = response.json()
        self._access_token = body["access_token"]
        self._token_expires_at = self._clock() + int(body.get("expires_in", 2592000)) - 60

    def _build_request(self, query: str) -> httpx.Request:
        self._ensure_token()
        return httpx.Request(
            "POST",
            self.SEARCH_URL,
            params={"access_token": self._access_token},
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"query": query, "count": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        body = response.json()
        errno = body.get("errno", 0)
        if errno != 0:
            raise ProviderError("upstream_failed", f"qianfan_errno_{errno}")
        items = body.get("data", {}).get("items", [])
        rows: list[dict] = []
        for item in items:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("title", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("abstract", "") or "",
                "content_type": "news",
                "published_at": item.get("publishTime", "") or "",
                "metrics": {},
            })
        return rows