import json

import httpx
import pytest

from src.search_discovery.providers_qianfan import QianfanSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("QIANFAN_API_KEY", raising=False)
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    assert QianfanSearchProvider.from_env() is None


def test_from_env_returns_none_when_only_one(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "legacy-ak")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    assert QianfanSearchProvider.from_env() is None


def test_from_env_accepts_new_single_api_key(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "bce-v3/ALTAK-new")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    p = QianfanSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "baidu_qianfan_search"


def test_from_env_returns_instance(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "baidu_qianfan_search"


def test_search_rows_exchanges_token_then_calls(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()

    token_calls = {"n": 0}
    search_calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        if "oauth/2.0/token" in str(request.url):
            token_calls["n"] += 1
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 2592000})
        search_calls["n"] += 1
        assert str(request.url) == "https://qianfan.baidubce.com/v2/ai_search/web_search"
        assert request.headers.get("Authorization") == "Bearer tok-1"
        assert json.loads(request.content) == {
            "messages": [{"content": "AI", "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": 10}],
        }
        return httpx.Response(200, json={
            "references": [
                {"title": "百度结果", "url": "https://example.com/x", "snippet": "摘要", "date": "2026-06-30"}
            ]
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("AI", keyword_category="topic_discovery",
                         fetched_at="2026-06-27T10:00:00+08:00")
    assert token_calls["n"] == 1
    assert search_calls["n"] == 1
    assert len(rows) == 1
    assert rows[0]["title"] == "百度结果"
    assert rows[0]["content_type"] == "web"
    assert rows[0]["published_at"] == "2026-06-30"


def test_search_rows_uses_single_api_key_as_bearer_without_token_exchange(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "bce-v3/ALTAK-new")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    p = QianfanSearchProvider.from_env()

    seen_urls = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        assert "oauth/2.0/token" not in str(request.url)
        assert request.headers.get("Authorization") == "Bearer bce-v3/ALTAK-new"
        assert json.loads(request.content) == {
            "messages": [{"content": "AI", "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": 10}],
        }
        return httpx.Response(200, json={
            "references": [
                {"title": "新版鉴权结果", "url": "https://example.com/new", "content": "摘要"}
            ]
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("AI")
    assert seen_urls == [
        "https://qianfan.baidubce.com/v2/ai_search/web_search"
    ]
    assert rows[0]["title"] == "新版鉴权结果"


def test_search_rows_accepts_minimal_result_limit(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "bce-v3/ALTAK-new")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    p = QianfanSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["resource_type_filter"] == [{"type": "web", "top_k": 1}]
        return httpx.Response(200, json={"references": []})

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)

    rows = p.search_rows("AI", max_results=1)

    assert rows == []


def test_search_rows_reuses_cached_token(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()
    p._access_token = "cached-tok"
    p._token_expires_at = 9_999_999_999  # far future

    search_calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        search_calls["n"] += 1
        if "oauth" in str(request.url):
            return httpx.Response(200, json={"access_token": "new", "expires_in": 1})
        assert request.headers.get("Authorization") == "Bearer cached-tok"
        return httpx.Response(200, json={"errno": 0, "data": {"items": []}})

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    p.search_rows("x")
    assert search_calls["n"] == 1


def test_search_rows_normalizes_nonzero_errno_to_error_row(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()
    p._access_token = "tok"
    p._token_expires_at = 9_999_999_999

    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"errno": 100, "msg": "err"})),
        timeout=p.timeout_seconds,
    )
    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "qianfan_errno_100"
    assert rows[0]["source_id"] == "baidu_qianfan_search"


def test_search_rows_normalizes_new_api_code_to_error_row(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "bce-v3/ALTAK-new")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    p = QianfanSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "code": 216003,
            "message": "Authentication error",
        })),
        timeout=p.timeout_seconds,
    )

    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")

    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "auth_failed"
    assert rows[0]["error_type"] == "qianfan_code_216003"


def test_search_rows_normalizes_error_code_to_error_row(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "bce-v3/ALTAK-new")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    p = QianfanSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "error_code": 3,
            "error_msg": "Unsupported openapi method",
        })),
        timeout=p.timeout_seconds,
    )

    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")

    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "qianfan_error_code_3"


def test_token_exchange_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()

    token_calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        if "oauth/2.0/token" in str(request.url):
            token_calls["n"] += 1
            if token_calls["n"] == 1:
                return httpx.Response(503, json={"error": "transient"})
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 2592000})
        return httpx.Response(200, json={"errno": 0, "data": {"items": []}})

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    # Avoid real sleep in retry backoff.
    monkeypatch.setattr("src.search_discovery.providers_qianfan.time.sleep", lambda _s: None)
    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")
    assert token_calls["n"] == 2
    assert rows == []


def test_token_exchange_does_not_retry_on_401(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()

    token_calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        token_calls["n"] += 1
        return httpx.Response(401, json={"error": "invalid_client"})

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    monkeypatch.setattr("src.search_discovery.providers_qianfan.time.sleep", lambda _s: None)
    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00", index=3)
    assert rows == [
            {
                "result_id": "baidu_qianfan_search_error_3",
                "source_id": "baidu_qianfan_search",
                "search_engine": "Baidu Qianfan Search",
                "source_role": "",
            "query": "x",
            "keyword_category": "unknown",
            "title": "",
            "url": "",
            "domain": "",
            "snippet": "",
            "content_type": "unknown",
            "published_at": "",
            "fetched_at": "2026-06-27T10:00:00+08:00",
            "metrics": {},
            "raw_payload": {},
            "fetch_status": "auth_failed",
            "error_type": "qianfan_token_invalid_client",
        }
    ]
    assert token_calls["n"] == 1


def test_token_exchange_preserves_upstream_auth_error(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "invalid_client", "error_description": "unknown client id"},
        )

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "auth_failed"
    assert rows[0]["error_type"] == "qianfan_token_invalid_client"
