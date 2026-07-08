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
    SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str = "",
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
        secret_key = os.getenv("QIANFAN_SECRET_KEY", "")
        if not api_key:
            return None
        if not secret_key and not cls._is_single_api_key(api_key):
            return None
        return cls(api_key=api_key, secret_key=secret_key)

    @staticmethod
    def _is_single_api_key(api_key: str) -> bool:
        return api_key.startswith("bce-v3/")

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
        # Token exchange can briefly blip (5xx, timeout). Retry those
        # transient cases, but do NOT retry 401/403 (permanent auth).
        last_exc: ProviderError | None = None
        for attempt in range(2):
            try:
                response = self._client.send(request)
            except httpx.TimeoutException:
                last_exc = ProviderError("auth_failed", "token_exchange_failed")
                if attempt == 0:
                    time.sleep(1)
                continue
            except httpx.TransportError:
                last_exc = ProviderError("auth_failed", "token_exchange_failed")
                if attempt == 0:
                    time.sleep(1)
                continue

            status = response.status_code
            if status == 401 or status == 403:
                raise ProviderError("auth_failed", self._token_error_type(response))
            if 500 <= status < 600:
                last_exc = ProviderError("auth_failed", "token_exchange_failed")
                if attempt == 0:
                    time.sleep(1)
                continue
            if status != 200:
                raise ProviderError("auth_failed", self._token_error_type(response))
            body = response.json()
            self._access_token = body["access_token"]
            self._token_expires_at = self._clock() + int(body.get("expires_in", 2592000)) - 60
            return
        # All attempts exhausted
        if last_exc is not None:
            raise last_exc
        raise ProviderError("auth_failed", "token_exchange_failed")

    def _token_error_type(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except Exception:
            return "token_exchange_failed"
        upstream_error = str(body.get("error", "")).strip()
        if upstream_error:
            return f"qianfan_token_{upstream_error}"
        return "token_exchange_failed"

    def _build_request(self, query: str, *, max_results: int = 10) -> httpx.Request:
        if self._is_single_api_key(self._api_key):
            access_token = self._api_key
        else:
            self._ensure_token()
            access_token = self._access_token
        return httpx.Request(
            "POST",
            self.SEARCH_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps({
                "messages": [{"content": query, "role": "user"}],
                "search_source": "baidu_search_v2",
                "resource_type_filter": [{"type": "web", "top_k": max(1, min(max_results, 10))}],
            }),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        code = body.get("code")
        if code not in (None, 0):
            status = "auth_failed" if str(code).startswith("216") else "upstream_failed"
            raise ProviderError(status, f"qianfan_code_{code}")
        error_code = body.get("error_code")
        if error_code not in (None, 0):
            raise ProviderError("upstream_failed", f"qianfan_error_code_{error_code}")
        errno = body.get("errno", 0)
        if errno != 0:
            raise ProviderError("upstream_failed", f"qianfan_errno_{errno}")
        items = body.get("references", [])
        if not items:
            items = body.get("data", {}).get("items", [])
        rows: list[dict[str, object]] = []
        for item in items:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("title", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("snippet", "") or item.get("content", "") or item.get("abstract", "") or "",
                "content_type": item.get("type", "") or "web",
                "published_at": item.get("date", "") or item.get("publishTime", "") or "",
                "metrics": {},
            })
        return rows
