import httpx

from src.search_discovery.providers_bocha import BochaSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    assert BochaSearchProvider.from_env() is None


def test_from_env_returns_instance_when_key_present(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "news_api_cn"


def test_search_rows_parses_webpages(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer sk-fake"
        body = request.read()
        import json as _json
        payload = _json.loads(body)
        assert payload["query"] == "AI Agent"
        return httpx.Response(200, json={
            "code": 0,
            "data": {
                "webPages": {
                    "value": [
                        {"name": "标题1", "url": "https://news.example.com/a",
                         "snippet": "摘要1", "datePublished": "2026-06-27"}
                    ]
                }
            }
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("AI Agent", keyword_category="topic_discovery",
                         fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["title"] == "标题1"
    assert rows[0]["url"] == "https://news.example.com/a"
    assert rows[0]["snippet"] == "摘要1"
    assert rows[0]["content_type"] == "news"
    assert rows[0]["published_at"] == "2026-06-27"


def test_search_rows_normalizes_non_zero_code_to_error_row(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"code": 4001, "msg": "quota"})),
        timeout=p.timeout_seconds,
    )
    rows = p.search_rows("x", fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "bocha_code_4001"
    assert rows[0]["source_id"] == "news_api_cn"


def test_search_rows_empty_results(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"code": 0, "data": {"webPages": {"value": []}}})),
        timeout=p.timeout_seconds,
    )
    assert p.search_rows("x") == []