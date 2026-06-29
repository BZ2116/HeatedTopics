import httpx

from src.search_discovery.providers_qiniu import QiniuWebSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("QINIU_WEB_SEARCH_API_KEY", raising=False)
    assert QiniuWebSearchProvider.from_env() is None


def test_search_rows_parses_qiniu_webpages(monkeypatch):
    monkeypatch.setenv("QINIU_WEB_SEARCH_API_KEY", "fake")
    provider = QiniuWebSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        assert "AI Agent" in payload
        assert request.headers["Authorization"] == "Bearer fake"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": "AI Agent 行业动态",
                                "url": "https://example.cn/article/1",
                                "snippet": "行业动态摘要",
                                "datePublished": "2026-06-29T10:00:00+08:00",
                            }
                        ]
                    }
                },
            },
        )

    provider._client = httpx.Client(transport=_transport(responder), timeout=provider.timeout_seconds)

    rows = provider.search_rows("AI Agent")

    assert rows[0]["title"] == "AI Agent 行业动态"
    assert rows[0]["url"] == "https://example.cn/article/1"
    assert rows[0]["snippet"] == "行业动态摘要"
    assert rows[0]["content_type"] == "article"
    assert rows[0]["published_at"] == "2026-06-29T10:00:00+08:00"
