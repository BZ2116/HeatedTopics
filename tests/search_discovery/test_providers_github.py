import httpx
import pytest

from src.search_discovery.providers_github import GitHubSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert GitHubSearchProvider.from_env() is None


def test_from_env_returns_instance_when_token_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    assert provider is not None
    assert provider.source_id == "github_search"


def test_search_rows_parses_items(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    provider._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "items": [
                {"full_name": "foo/bar", "html_url": "https://github.com/foo/bar",
                 "description": "desc", "stargazers_count": 100}
            ]
        })),
        timeout=provider.timeout_seconds,
    )
    rows = provider.search_rows("agent", keyword_category="tech_project", fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["title"] == "foo/bar"
    assert rows[0]["url"] == "https://github.com/foo/bar"
    assert rows[0]["snippet"] == "desc"
    assert rows[0]["content_type"] == "repo"
    assert rows[0]["metrics"]["stars"] == 100


def test_search_rows_empty_items(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    provider._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"items": []})),
        timeout=provider.timeout_seconds,
    )
    rows = provider.search_rows("nothing")
    assert rows == []


def test_search_rows_skips_items_without_url(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    provider._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "items": [
                {"full_name": "ok/x", "html_url": "https://github.com/ok/x", "description": "d"},
                {"full_name": "bad", "html_url": "", "description": "no url"},
            ]
        })),
        timeout=provider.timeout_seconds,
    )
    rows = provider.search_rows("x")
    assert len(rows) == 1
    assert rows[0]["title"] == "ok/x"