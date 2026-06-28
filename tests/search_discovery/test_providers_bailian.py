import httpx
import pytest

from src.search_discovery.providers_bailian import BailianWebSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("BAILIAN_API_KEY", raising=False)
    assert BailianWebSearchProvider.from_env() is None


def test_from_env_returns_instance(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "juejin_content"


def test_search_rows_parses_results(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer sk-fake"
        return httpx.Response(200, json={
            "output": {
                "search_results": [
                    {"title": "深度文章", "url": "https://example.com/a",
                     "snippet": "摘要", "content_type": "article"}
                ]
            }
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("RAG")
    assert len(rows) == 1
    assert rows[0]["title"] == "深度文章"
    assert rows[0]["content_type"] == "article"


def test_search_rows_empty(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"output": {"search_results": []}})),
        timeout=p.timeout_seconds,
    )
    assert p.search_rows("x") == []


def test_search_rows_normalizes_nonzero_code_to_error_row(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "code": 400,
            "message": "InvalidArgument",
        })),
        timeout=p.timeout_seconds,
    )
    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "bailian_code_400"
    assert rows[0]["source_id"] == "juejin_content"