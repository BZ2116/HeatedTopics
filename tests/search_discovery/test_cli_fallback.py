import json

from src.search_discovery.cli import _build_registry, _emit_unavailable_markers
from src.search_discovery.types import CreatorProfile


def _profile():
    return CreatorProfile.from_dict({
        "creator_id": "t", "role": "科技博主", "profile_type": "tech_ai_creator",
        "track_tags": ["AI"], "custom_keywords": ["Agent"], "content_modes": [],
    })


def test_build_registry_uses_mock_when_no_keys(monkeypatch):
    for key in ("GITHUB_TOKEN", "BOCHA_API_KEY", "BAILIAN_API_KEY",
                "QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    registry = _build_registry()
    for sid in ("github_search", "news_api_cn", "juejin_content", "baidu_qianfan_search"):
        assert sid in registry._providers


def test_emit_unavailable_markers_returns_four_rows():
    rows = _emit_unavailable_markers(
        registry_source_ids=["github_search", "news_api_cn", "juejin_content", "baidu_qianfan_search"],
        query="AI", category="topic_discovery", fetched_at="2026-06-27T10:00:00+08:00",
        index=7,
    )
    assert len(rows) == 4
    assert all(r["fetch_status"] == "mock_unavailable" for r in rows)
    assert all(r["error_type"] == "missing_key" for r in rows)
    assert all(r["result_id"].endswith("_7") for r in rows)


def test_build_registry_uses_real_when_keys_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    for key in ("BOCHA_API_KEY", "BAILIAN_API_KEY",
                "QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    registry = _build_registry()
    from src.search_discovery.providers_github import GitHubSearchProvider
    assert isinstance(registry._providers["github_search"], GitHubSearchProvider)
    # others should be mock
    from src.search_discovery.providers import MockProvider
    assert isinstance(registry._providers["news_api_cn"], MockProvider)
