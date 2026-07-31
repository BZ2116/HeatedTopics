"""Tests for source dispatch in recommender."""

from __future__ import annotations

from pathlib import Path

from heated_topics_v3.openbiliclaw_integration import recommender


def _make_spec():
    """Minimal UserSpec-like dict for dispatch tests."""
    from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec

    return UserSpec(
        user_id="u_test",
        display_name="Test",
        interests=[],
        disliked_topics=[],
        core_traits=[],
        deep_needs=[],
        values=[],
        recent_awareness=[],
        active_insights=[],
    )


def test_source_v3_hotlist_only_invokes_v3(monkeypatch) -> None:
    """Default source: only V3 fetch_candidates runs."""
    spec = _make_spec()
    called = {"v3": 0, "l30": 0}

    def fake_v3(*args, **kwargs):
        called["v3"] += 1
        return []

    def fake_l30(*args, **kwargs):
        called["l30"] += 1
        return []

    monkeypatch.setattr(recommender, "fetch_candidates", fake_v3)
    monkeypatch.setattr(recommender, "_fetch_last30days_candidates", fake_l30)

    out = recommender._fetch_candidates_for_user(
        spec=spec,
        source="v3-hotlist",
        last30days_config=None,
    )
    assert out == []
    assert called == {"v3": 1, "l30": 0}


def test_source_last30days_only_invokes_l30(monkeypatch) -> None:
    spec = _make_spec()
    called = {"v3": 0, "l30": 0}

    def fake_v3(*args, **kwargs):
        called["v3"] += 1
        raise AssertionError("v3 should not run")

    def fake_l30(*args, **kwargs):
        called["l30"] += 1
        return []

    monkeypatch.setattr(recommender, "fetch_candidates", fake_v3)
    monkeypatch.setattr(recommender, "_fetch_last30days_candidates", fake_l30)

    cfg = {"cli_path": Path("/fake"), "query": "x", "days": 30}
    out = recommender._fetch_candidates_for_user(
        spec=spec, source="last30days", last30days_config=cfg,
    )
    assert out == []
    assert called == {"v3": 0, "l30": 1}


def test_source_last30days_requires_config() -> None:
    """When source=last30days but no config, return [] (don't crash)."""
    spec = _make_spec()
    out = recommender._fetch_candidates_for_user(
        spec=spec, source="last30days", last30days_config=None,
    )
    assert out == []


def test_source_both_merges_with_url_dedup(monkeypatch) -> None:
    """When source=both, v3 wins on URL collision."""
    spec = _make_spec()
    shared_url = "https://example.com/dup"
    v3_articles = [
        {
            "article_id": "v3:1", "title": "t", "url": shared_url,
            "body_text": "v3 body", "summary": "", "author": "",
            "published_at": "", "tags": [], "heat": {"rank": 1},
            "platform": "toutiao",
        }
    ]
    l30_articles = [
        {
            "article_id": "l30:1", "title": "t", "url": shared_url,
            "body_text": "l30 body", "summary": "", "author": "",
            "published_at": "", "tags": [], "heat": {"rank": 1},
            "platform": "toutiao",
        },
        {
            "article_id": "l30:2", "title": "u", "url": "https://example.com/uniq",
            "body_text": "", "summary": "", "author": "",
            "published_at": "", "tags": [], "heat": {},
            "platform": "weibo",
        },
    ]

    monkeypatch.setattr(recommender, "fetch_candidates", lambda *a, **k: v3_articles)
    monkeypatch.setattr(recommender, "_fetch_last30days_candidates",
                        lambda *a, **k: l30_articles)

    cfg = {"cli_path": Path("/fake"), "query": "x", "days": 30}
    out = recommender._fetch_candidates_for_user(
        spec=spec, source="both", last30days_config=cfg,
    )
    assert len(out) == 2
    ids = [a["article_id"] for a in out]
    # v3:1 kept (URL collision), l30:2 appended
    assert ids == ["v3:1", "l30:2"]


def test_fetch_last30days_candidates_returns_list_dict(monkeypatch, tmp_path) -> None:
    """_fetch_last30days_candidates returns list of article dicts (not HotItem)."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "query": "AI",
        "days": 30,
        "fetch_bodies": True,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }

    fake_report = {"weibo": [], "zhihu": [], "topic": "AI"}
    fake_report_path = tmp_path / "out" / "report.json"
    fake_report_path.parent.mkdir(parents=True, exist_ok=True)
    fake_report_path.write_text(json.dumps(fake_report), encoding="utf-8")

    monkeypatch.setattr(
        recommender.last30days_source, "_run_subprocess",
        lambda *a, **k: fake_report_path,
    )
    out = recommender._fetch_last30days_candidates(spec, cfg)
    assert out == []


import json  # noqa: E402