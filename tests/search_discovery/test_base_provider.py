import time
from src.search_discovery.base_provider import TokenBucket


def test_token_bucket_first_call_no_sleep():
    bucket = TokenBucket(rpm=60, sleep=lambda _: None)
    bucket.acquire()
    # No assertion needed — the test passes if no exception / no real sleep.


def test_token_bucket_second_call_sleeps_to_interval():
    sleeps: list[float] = []
    bucket = TokenBucket(rpm=60, sleep=lambda s: sleeps.append(s))
    bucket.acquire()
    bucket.acquire()
    assert len(sleeps) == 1
    assert 0.99 <= sleeps[0] <= 1.01  # 60 RPM = 1 second interval


def test_token_bucket_respects_rpm_30():
    sleeps: list[float] = []
    bucket = TokenBucket(rpm=30, sleep=lambda s: sleeps.append(s))
    bucket.acquire()
    bucket.acquire()
    assert len(sleeps) == 1
    assert 1.99 <= sleeps[0] <= 2.01  # 30 RPM = 2 second interval


import httpx
import pytest

from src.search_discovery.base_provider import (
    BaseHTTPSearchProvider,
    ProviderError,
    make_error_row,
)


class _FakeProvider(BaseHTTPSearchProvider):
    source_id = "fake"
    rpm_limit = 6000  # effectively no throttling in tests

    def __init__(self, transport: httpx.MockTransport, **kwargs):
        super().__init__(transport=transport, **kwargs)

    @classmethod
    def from_env(cls):
        return cls(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []})))

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request("GET", "https://example.test/search", params={"q": query})

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        return response.json().get("items", [])


def _transport(responder):
    return httpx.MockTransport(responder)


def test_success_returns_rows():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(200, json={"items": [{"title": "x"}]})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows == [{"title": "x"}]


def test_401_returns_auth_failed_row():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(401, json={"err": "no"})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "auth_failed"
    assert rows[0]["error_type"] == "unauthorized"
    assert rows[0]["keyword_category"] == "topic_discovery"


def test_403_returns_auth_failed_row():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(403, json={"err": "no"})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "auth_failed"
    assert rows[0]["error_type"] == "forbidden"


def test_429_with_retry_after_is_retried():
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"err": "limit"})
        return httpx.Response(200, json={"items": [{"title": "ok"}]})

    provider = _FakeProvider(_transport(responder))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert calls["n"] == 3
    assert rows == [{"title": "ok"}]


def test_5xx_retried_then_succeeds():
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, json={"err": "boom"})
        return httpx.Response(200, json={"items": [{"title": "ok"}]})

    sleeps: list[float] = []
    provider = _FakeProvider(_transport(responder), bucket_sleep=lambda s: sleeps.append(s))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert calls["n"] == 2
    assert rows == [{"title": "ok"}]
    # First backoff = 1 second; second would be 2 (not reached).
    assert sleeps and 0.9 <= sleeps[0] <= 1.1


def test_5xx_exhausted_returns_upstream_failed():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(500, json={"err": "boom"})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "server_error"


def test_timeout_returns_upstream_failed():
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated")

    provider = _FakeProvider(_transport(responder))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "timeout"


def test_parse_error_returns_parse_failed():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(200, text="not json")))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "parse_failed"
    assert rows[0]["error_type"] == "invalid_json"


def test_make_error_row_helper():
    row = make_error_row(source_id="x", query="q", category="tech_project",
                         fetch_status="auth_failed", error_type="unauthorized",
                         fetched_at="2026-06-27T10:00:00+08:00", index=2)
    assert row["source_id"] == "x"
    assert row["fetch_status"] == "auth_failed"
    assert row["query"] == "q"
    assert row["keyword_category"] == "tech_project"
    assert row["title"] == ""
    assert row["url"] == ""
    assert row["result_id"] == "x_error_2"


class _BaseDefaultParser(BaseHTTPSearchProvider):
    """Uses the base class's default _parse_response unchanged."""
    source_id = "base_default"
    rpm_limit = 6000

    def __init__(self, transport, **kwargs):
        super().__init__(transport=transport, **kwargs)

    @classmethod
    def from_env(cls):
        return cls(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))

    def _build_request(self, query):
        return httpx.Request("GET", "https://example.test/", params={"q": query})


def test_base_parse_response_normalizes_non_json_to_parse_failed():
    provider = _BaseDefaultParser(_transport(lambda r: httpx.Response(200, text="not json")))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "parse_failed"
    assert rows[0]["error_type"] == "invalid_json"