"""Tests for source dispatch in recommender (v2 UserSpec)."""

from __future__ import annotations

import json
from pathlib import Path

from heated_topics_v3.openbiliclaw_integration import recommender
from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec


def _make_spec(user_id: str = "u_test") -> UserSpec:
    """Minimal v2 UserSpec — no interests/core_traits/etc."""
    return UserSpec(
        user_id=user_id,
        display_name=user_id,
        track_1="AI",
        track_2="副业",
        persona="博主",
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


def test_first_track_returns_track_1_when_set() -> None:
    spec = UserSpec(user_id="u", track_1="AI", track_2="副业", persona="")
    assert recommender._first_track(spec) == "AI"


def test_first_track_returns_track_1_even_when_track_2_empty() -> None:
    spec = UserSpec(user_id="u", track_1="AI", track_2="", persona="")
    assert recommender._first_track(spec) == "AI"


# ---- multi-query (v2.1.5) --------------------------------------------------


def test_resolve_last30days_queries_cfg_queries_wins(monkeypatch) -> None:
    """Explicit cfg['queries'] always wins over LLM keywords or single query."""
    spec = _make_spec()
    cfg = {
        "cli_path": Path("/fake"),
        "queries": ["A", "B"],
        "query": "X",
    }
    queries = recommender._resolve_last30days_queries(
        cfg, keywords=["K1", "K2", "K3"], spec=spec, max_queries=3,
    )
    assert queries == ["A", "B"]


def test_resolve_last30days_queries_cfg_query_legacy(monkeypatch) -> None:
    """Legacy cfg['query'] becomes a single-query list."""
    spec = _make_spec()
    cfg = {"cli_path": Path("/fake"), "query": "X"}
    queries = recommender._resolve_last30days_queries(
        cfg, keywords=["K1", "K2", "K3"], spec=spec, max_queries=3,
    )
    assert queries == ["X"]


def test_resolve_last30days_queries_keywords_when_no_cfg_override(monkeypatch) -> None:
    """LLM-extracted keywords feed in when no cfg override."""
    spec = _make_spec()
    cfg = {"cli_path": Path("/fake")}
    queries = recommender._resolve_last30days_queries(
        cfg, keywords=["K1", "K2", "K3", "K4"], spec=spec, max_queries=3,
    )
    assert queries == ["K1", "K2", "K3"]


def test_resolve_last30days_queries_falls_back_to_tracks(monkeypatch) -> None:
    """When keywords is empty, fall back to spec tracks."""
    spec = _make_spec()
    cfg = {"cli_path": Path("/fake")}
    queries = recommender._resolve_last30days_queries(
        cfg, keywords=None, spec=spec, max_queries=3,
    )
    assert queries == ["AI", "副业"]


def test_fetch_last30days_runs_one_subprocess_per_query(monkeypatch, tmp_path) -> None:
    """Each resolved query becomes one CLI invocation."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["古典文学", "古文", "诗词"],
        "days": 30,
        "fetch_bodies": True,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }

    calls: list[str] = []
    report_template = {"weibo": [], "zhihu": [], "topic": "x"}

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        calls.append(query)
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        out.write_text(json.dumps({**report_template, "topic": query}), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    out = recommender._fetch_last30days_candidates(spec, cfg)
    assert calls == ["古典文学", "古文", "诗词"]
    assert out == []


def test_fetch_last30days_dedups_urls_across_queries(monkeypatch, tmp_path) -> None:
    """Same URL appearing in two query results is kept once."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["古典文学", "诗词"],
        "days": 30,
        "fetch_bodies": True,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }
    shared_url = "https://weibo.com/dup"

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        save_dir.mkdir(parents=True, exist_ok=True)
        if query == "古典文学":
            payload = {
                "weibo": [
                    {"id": "1", "text": "Q1 item", "url": shared_url,
                     "engagement": {"views": 100, "likes": 5}},
                    {"id": "2", "text": "Q1 unique", "url": "https://weibo.com/q1u",
                     "engagement": {"views": 200, "likes": 10}},
                ],
                "topic": query,
            }
        else:
            payload = {
                "weibo": [
                    {"id": "1", "text": "Q2 dup", "url": shared_url,
                     "engagement": {"views": 999, "likes": 99}},
                    {"id": "3", "text": "Q2 unique", "url": "https://weibo.com/q2u",
                     "engagement": {"views": 50, "likes": 1}},
                ],
                "topic": query,
            }
        out = save_dir / "report.json"
        out.write_text(json.dumps(payload), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    articles = recommender._fetch_last30days_candidates(spec, cfg)
    urls = [a["url"] for a in articles]
    assert urls.count(shared_url) == 1, urls
    assert len(urls) == 3  # shared + 2 unique
    # The winning version is the first query that surfaced it (古典文学).
    for a in articles:
        if a["url"] == shared_url:
            assert a["search_query"] == "古典文学"
            assert a["heat"]["view"] == 100


def test_fetch_last30days_max_queries_caps(monkeypatch, tmp_path) -> None:
    """max_queries caps the total CLI invocations."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["a", "b", "c", "d", "e"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }
    calls: list[str] = []

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        calls.append(query)
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        out.write_text(json.dumps({"weibo": [], "topic": query}), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    recommender._fetch_last30days_candidates(spec, cfg, max_queries=2)
    assert calls == ["a", "b"]


def test_fetch_last30days_uses_keywords_when_no_cfg_override(
    monkeypatch, tmp_path
) -> None:
    """Without cfg['queries']/['query'], LLM keywords drive the queries."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }
    calls: list[str] = []

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        calls.append(query)
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        out.write_text(json.dumps({"weibo": [], "topic": query}), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    recommender._fetch_last30days_candidates(
        spec, cfg, keywords=["古文", "诗词", "唐诗"],
    )
    assert calls == ["古文", "诗词", "唐诗"]


def test_fetch_last30days_continues_after_one_query_fails(
    monkeypatch, tmp_path
) -> None:
    """Failure in one query doesn't poison the rest."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["good", "bad", "good2"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        if query == "bad":
            raise RuntimeError("synthetic subprocess crash")
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        out.write_text(json.dumps({"weibo": [], "topic": query}), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    articles = recommender._fetch_last30days_candidates(spec, cfg)
    # bad query is silently skipped; the other two return empty arrays.
    assert articles == []


# ---- adaptive escalation (v2.1.5) ------------------------------------------


def _make_qn_runner(per_query_items: dict[str, list[dict]]) -> callable:
    """Build a fake last30days_source.run that returns a different report per
    query. ``per_query_items`` maps query → list of raw weibo item dicts.
    Queries not in the map return empty reports.
    """
    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        payload = {"weibo": per_query_items.get(query, []), "topic": query}
        out.write_text(json.dumps(payload), encoding="utf-8")
        return out
    return fake_run


def test_fetch_last30days_stops_early_when_first_query_yields_enough(
    monkeypatch, tmp_path
) -> None:
    """When the first query already exceeds low_water_mark, subsequent
    queries are skipped (no redundant subprocess)."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["q1", "q2", "q3"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
        "low_water_mark": 3,
    }
    # q1 returns 5 items — enough on its own.
    q1_items = [
        {"id": str(i), "text": f"item {i}", "url": f"https://w.com/{i}",
         "engagement": {"views": 100, "likes": 1}}
        for i in range(5)
    ]
    calls: list[str] = []
    real_runner = _make_qn_runner({"q1": q1_items})

    def spy_run(*, cli_path, query, **kwargs):
        calls.append(query)
        return real_runner(cli_path=cli_path, query=query, **kwargs)

    monkeypatch.setattr(recommender.last30days_source, "run", spy_run)
    articles = recommender._fetch_last30days_candidates(spec, cfg)
    assert calls == ["q1"], f"expected only q1 to run, got {calls}"
    assert len(articles) == 5


def test_fetch_last30days_escalates_when_first_query_is_thin(
    monkeypatch, tmp_path
) -> None:
    """If the first query yields <= low_water_mark, the next query is
    tried. If cumulative now exceeds threshold, stop."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["q1", "q2", "q3"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
        "low_water_mark": 3,
    }
    # q1 returns 1 item (≤ 3), q2 returns 4 unique items (cumulative 5 > 3).
    q1_items = [
        {"id": "a", "text": "a", "url": "https://w.com/a",
         "engagement": {"views": 10, "likes": 1}},
    ]
    q2_items = [
        {"id": f"b{i}", "text": f"b{i}", "url": f"https://w.com/b{i}",
         "engagement": {"views": 10, "likes": 1}}
        for i in range(4)
    ]
    calls: list[str] = []
    real_runner = _make_qn_runner({"q1": q1_items, "q2": q2_items})

    def spy_run(*, cli_path, query, **kwargs):
        calls.append(query)
        return real_runner(cli_path=cli_path, query=query, **kwargs)

    monkeypatch.setattr(recommender.last30days_source, "run", spy_run)
    articles = recommender._fetch_last30days_candidates(spec, cfg)
    assert calls == ["q1", "q2"], f"expected escalation to q2 only, got {calls}"
    assert len(articles) == 5  # 1 + 4 unique


def test_fetch_last30days_runs_all_when_all_queries_are_thin(
    monkeypatch, tmp_path
) -> None:
    """If cumulative never exceeds low_water_mark, all queries run."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["q1", "q2", "q3"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
        "low_water_mark": 10,
    }
    calls: list[str] = []

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        calls.append(query)
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        # Each query returns 1 item — cumulative stays below threshold.
        out.write_text(json.dumps({
            "weibo": [
                {"id": f"{query}-1", "text": "x", "url": f"https://w.com/{query}",
                 "engagement": {"views": 1}},
            ],
            "topic": query,
        }), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    articles = recommender._fetch_last30days_candidates(spec, cfg)
    assert calls == ["q1", "q2", "q3"]
    assert len(articles) == 3


def test_fetch_last30days_default_low_water_mark_is_three(
    monkeypatch, tmp_path
) -> None:
    """Without cfg['low_water_mark'], the default of 3 applies."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["q1", "q2"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
    }
    # q1 returns exactly 4 items — 4 > 3 default → stop.
    q1_items = [
        {"id": str(i), "text": f"x{i}", "url": f"https://w.com/{i}",
         "engagement": {"views": 1}}
        for i in range(4)
    ]
    calls: list[str] = []
    real_runner = _make_qn_runner({"q1": q1_items})

    def spy_run(*, cli_path, query, **kwargs):
        calls.append(query)
        return real_runner(cli_path=cli_path, query=query, **kwargs)

    monkeypatch.setattr(recommender.last30days_source, "run", spy_run)
    recommender._fetch_last30days_candidates(spec, cfg)
    assert calls == ["q1"]


def test_fetch_last30days_failed_query_counts_as_zero_for_escalation(
    monkeypatch, tmp_path
) -> None:
    """A failed query still escalates to the next, since it returns 0."""
    spec = _make_spec()
    cfg = {
        "cli_path": tmp_path / "last30days.py",
        "queries": ["good", "bad", "good2"],
        "days": 30,
        "platforms": (),
        "timeout": 30.0,
        "save_dir": tmp_path / "out",
        "low_water_mark": 3,
    }
    # good returns 5 (exceeds threshold, should stop after this).
    good_items = [
        {"id": str(i), "text": "x", "url": f"https://w.com/{i}",
         "engagement": {"views": 1}}
        for i in range(5)
    ]
    calls: list[str] = []

    def fake_run(*, cli_path, query, days, save_dir, fetch_bodies, platforms, timeout):
        calls.append(query)
        if query == "bad":
            raise RuntimeError("synthetic crash")
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / "report.json"
        items = good_items if query == "good" else []
        out.write_text(json.dumps({"weibo": items, "topic": query}), encoding="utf-8")
        return out

    monkeypatch.setattr(recommender.last30days_source, "run", fake_run)
    articles = recommender._fetch_last30days_candidates(spec, cfg)
    assert calls == ["good"], f"early-stop on good should skip bad/good2, got {calls}"
    assert len(articles) == 5
