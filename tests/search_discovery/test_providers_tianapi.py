import httpx

from src.search_discovery.providers_tianapi import TianAPINewsProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("TIANAPI_KEY", raising=False)
    assert TianAPINewsProvider.from_env() is None


def test_search_rows_parses_tianapi_news(monkeypatch):
    monkeypatch.setenv("TIANAPI_KEY", "fake")
    provider = TianAPINewsProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "fake"
        assert request.url.params["word"] == "AI Agent"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "newslist": [
                    {
                        "title": "AI Agent 国内应用发布",
                        "url": "https://example.cn/news/1",
                        "description": "AI Agent 应用发布摘要",
                        "ctime": "2026-06-29 10:00",
                        "source": "示例媒体",
                    }
                ],
            },
        )

    provider._client = httpx.Client(transport=_transport(responder), timeout=provider.timeout_seconds)

    rows = provider.search_rows("AI Agent")

    assert rows[0]["title"] == "AI Agent 国内应用发布"
    assert rows[0]["url"] == "https://example.cn/news/1"
    assert rows[0]["snippet"] == "AI Agent 应用发布摘要"
    assert rows[0]["content_type"] == "news"
    assert rows[0]["published_at"] == "2026-06-29 10:00"
    assert rows[0]["raw_payload"]["source"] == "示例媒体"
