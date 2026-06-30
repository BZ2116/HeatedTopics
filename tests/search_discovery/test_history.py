import json
from datetime import datetime, timezone

from src.search_discovery.history import (
    mark_recent_recommendations,
    read_recommendation_history,
    write_recommendation_history,
)
from src.search_discovery.types import SearchResult


def test_read_recommendation_history_returns_empty_when_missing(tmp_path):
    assert read_recommendation_history(tmp_path / "missing.json") == {}


def test_write_and_read_recommendation_history(tmp_path):
    path = tmp_path / "recommended_topics.json"
    payload = {
        "https://github.com/owner/repo": {
            "title": "owner/repo",
            "recommended_at": "2026-06-20T10:00:00+08:00",
            "source_id": "github_search",
        }
    }

    write_recommendation_history(path, payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert read_recommendation_history(path) == payload


def test_mark_recent_recommendations_sets_cooldown_metric():
    result = SearchResult(
        result_id="r1",
        source_id="github_search",
        source_role="vertical_project",
        query="agent",
        keyword_category="tech_project",
        title="owner/repo",
        url="https://github.com/owner/repo",
        snippet="desc",
        content_type="repo",
        metrics={"stars": 1200},
    )
    history = {
        "https://github.com/owner/repo": {
            "title": "owner/repo",
            "recommended_at": "2026-06-20T10:00:00+08:00",
            "source_id": "github_search",
        }
    }

    marked = mark_recent_recommendations(
        [result],
        history=history,
        now=datetime(2026, 6, 29, tzinfo=timezone.utc),
        cooldown_days=30,
    )

    assert marked[0].metrics["recently_recommended"] is True
    assert marked[0].metrics["last_recommended_at"] == "2026-06-20T10:00:00+08:00"
