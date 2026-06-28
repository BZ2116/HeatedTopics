import json

from src.search_discovery.cli import _build_registry, _emit_unavailable_markers, run_discovery_command
from src.search_discovery.providers_github import GitHubSearchProvider
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
        assert sid in registry.providers


def test_emit_unavailable_markers_returns_four_rows():
    rows = _emit_unavailable_markers(
        registry_source_ids=["github_search", "news_api_cn"],
        query="AI", category="topic_discovery", fetched_at="2026-06-27T10:00:00+08:00",
        index=7,
    )
    assert len(rows) == 2
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
    assert isinstance(registry.providers["github_search"], GitHubSearchProvider)
    # others should be mock
    from src.search_discovery.providers import MockProvider
    assert isinstance(registry.providers["news_api_cn"], MockProvider)


class _FailingGitHubProvider:
    source_id = "github_search"

    def search_rows(self, query, **kwargs):
        return [{
            "title": "", "url": "", "snippet": "", "content_type": "unknown",
            "fetch_status": "auth_failed", "error_type": "unauthorized",
        }]


def test_run_discovery_command_drops_non_ok_rows_from_topics(tmp_path, monkeypatch):
    for key in ("GITHUB_TOKEN", "BOCHA_API_KEY", "BAILIAN_API_KEY",
                "QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({
        "creator_id": "c1", "role": "科技博主", "profile_type": "tech_ai_creator",
        "track_tags": ["AI"], "custom_keywords": ["Agent"], "content_modes": [],
    }, ensure_ascii=False), encoding="utf-8")

    counts = run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=False)

    # raw rows may be > 0 (mock_unavailable markers are written),
    # but none of them should reach the topic index.
    assert counts["search_results_count"] > 0
    assert counts["topics_count"] == 0

    topic_index = json.loads(
        (tmp_path / "data/search_discovery/processed/search_topic_index.json").read_text(encoding="utf-8")
    )
    assert topic_index["topics"] == []


def test_failed_real_does_not_fallback_to_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setattr(
        GitHubSearchProvider, "from_env",
        classmethod(lambda cls: _FailingGitHubProvider()),
    )

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({
        "creator_id": "c1", "role": "科技博主", "profile_type": "tech_ai_creator",
        "track_tags": ["AI"], "custom_keywords": ["Agent"], "content_modes": [],
    }, ensure_ascii=False), encoding="utf-8")

    run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=False)

    raw_lines = (tmp_path / "data/search_discovery/raw/search_results.jsonl").read_text(
        encoding="utf-8").splitlines()
    raw_rows = [json.loads(line) for line in raw_lines]
    github_rows = [r for r in raw_rows if r["source_id"] == "github_search"]
    assert github_rows, "expected github rows to be written even on failure"
    assert not any(r["fetch_status"] == "mock_unavailable" for r in github_rows)
    assert all(r["fetch_status"] == "auth_failed" for r in github_rows)
