import time
from dataclasses import dataclass, field
from typing import Callable

import httpx


@dataclass
class TokenBucket:
    rpm: int
    sleep: Callable[[float], None] = time.sleep
    _last: float = field(default=0.0, init=False)

    def acquire(self) -> None:
        interval = 60.0 / self.rpm
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < interval and self._last > 0:
            self.sleep(interval - elapsed)
        self._last = time.monotonic()


class ProviderError(Exception):
    def __init__(self, fetch_status: str, error_type: str):
        super().__init__(f"{fetch_status}: {error_type}")
        self.fetch_status = fetch_status
        self.error_type = error_type


def make_error_row(
    *,
    source_id: str,
    query: str,
    category: str,
    fetch_status: str,
    error_type: str,
    fetched_at: str,
    index: int = 0,
) -> dict:
    return {
        "result_id": f"{source_id}_error_{index}",
        "source_id": source_id,
        "source_role": "",
        "query": query,
        "keyword_category": category,
        "title": "",
        "url": "",
        "domain": "",
        "snippet": "",
        "content_type": "unknown",
        "published_at": "",
        "fetched_at": fetched_at,
        "metrics": {},
        "raw_payload": {},
        "fetch_status": fetch_status,
        "error_type": error_type,
    }


class BaseHTTPSearchProvider:
    """Subclasses set `source_id` and `rpm_limit`, and implement
    `_build_request`, `_parse_response`, and `from_env`."""

    source_id: str = ""
    rpm_limit: int = 60
    timeout_seconds: float = 10.0
    max_retries: int = 3

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        bucket_sleep: Callable[[float], None] | None = None,
    ):
        self._client = httpx.Client(timeout=self.timeout_seconds, transport=transport)
        sleep_fn = bucket_sleep if bucket_sleep is not None else time.sleep
        self._bucket = TokenBucket(rpm=self.rpm_limit, sleep=sleep_fn)

    @classmethod
    def from_env(cls) -> "BaseHTTPSearchProvider | None":
        raise NotImplementedError

    def search_rows(
        self,
        query: str,
        *,
        keyword_category: str = "unknown",
        fetched_at: str = "",
        index: int = 0,
    ) -> list[dict]:
        request = self._build_request(query)
        self._bucket.acquire()
        try:
            response = self._execute_with_retry(request)
        except ProviderError as exc:
            return [make_error_row(
                source_id=self.source_id,
                query=query,
                category=keyword_category,
                fetch_status=exc.fetch_status,
                error_type=exc.error_type,
                fetched_at=fetched_at,
                index=index,
            )]
        try:
            return self._parse_response(response, query)
        except ProviderError as exc:
            return [make_error_row(
                source_id=self.source_id,
                query=query,
                category=keyword_category,
                fetch_status=exc.fetch_status,
                error_type=exc.error_type,
                fetched_at=fetched_at,
                index=index,
            )]
        except Exception:
            return [make_error_row(
                source_id=self.source_id,
                query=query,
                category=keyword_category,
                fetch_status="parse_failed",
                error_type="invalid_json",
                fetched_at=fetched_at,
                index=index,
            )]

    def _execute_with_retry(self, request: httpx.Request) -> httpx.Response:
        last_exc: ProviderError | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._client.send(request)
            except httpx.TimeoutException:
                last_exc = ProviderError("upstream_failed", "timeout")
                self._backoff(attempt)
                continue
            except httpx.TransportError:
                last_exc = ProviderError("upstream_failed", "network")
                self._backoff(attempt)
                continue

            status = response.status_code
            if status == 401:
                raise ProviderError("auth_failed", "unauthorized")
            if status == 403:
                raise ProviderError("auth_failed", "forbidden")
            if status == 429:
                if attempt < self.max_retries - 1:
                    wait = float(response.headers.get("Retry-After", "1"))
                    self._bucket.sleep(wait)
                    continue
                raise ProviderError("upstream_failed", "rate_limited")
            if 500 <= status < 600:
                last_exc = ProviderError("upstream_failed", "server_error")
                self._backoff(attempt)
                continue
            return response

        if last_exc is not None:
            raise last_exc
        raise ProviderError("upstream_failed", "exhausted")

    def _backoff(self, attempt: int) -> None:
        # 1s, 2s, 4s
        self._bucket.sleep(2 ** attempt)

    def _build_request(self, query: str) -> httpx.Request:
        raise NotImplementedError

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        try:
            return response.json()
        except Exception:
            raise ProviderError("parse_failed", "invalid_json")