import json

import httpx

from src.search_discovery.providers_tavily import TavilySearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert TavilySearchProvider.from_env() is None


def test_search_rows_parses_tavily_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly_fake")
    provider = TavilySearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode("utf-8"))
        assert request.headers["Authorization"] == "Bearer tvly_fake"
        assert payload["query"] == "AI Agent 最新进展"
        assert payload["topic"] == "news"
        assert payload["country"] == "china"
        assert payload["max_results"] == 10
        assert payload["include_raw_content"] is True
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "AI Agent 国内进展",
                        "url": "https://example.cn/news/agent",
                        "content": "AI Agent 国内进展摘要",
                        "raw_content": "AI Agent 国内进展详细内容",
                        "score": 0.91,
                        "published_date": "2026-06-30",
                    }
                ],
            },
        )

    provider._client = httpx.Client(transport=_transport(responder), timeout=provider.timeout_seconds)

    rows = provider.search_rows("AI Agent 最新进展")

    assert rows[0]["title"] == "AI Agent 国内进展"
    assert rows[0]["url"] == "https://example.cn/news/agent"
    assert rows[0]["snippet"] == "AI Agent 国内进展摘要"
    assert rows[0]["content_type"] == "news"
    assert rows[0]["published_at"] == "2026-06-30"
    assert rows[0]["metrics"]["score"] == 0.91
    assert rows[0]["raw_payload"]["raw_content"] == "AI Agent 国内进展详细内容"
