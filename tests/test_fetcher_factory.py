from pathlib import Path

import heated_topics_v3.fetcher_factory as fetcher_factory
from heated_topics_v3.fetcher_factory import SearchFetcher, _referer_for


def _fetcher(tmp_path: Path, *, paced: bool) -> SearchFetcher:
    instance = SearchFetcher(
        cookie_path=tmp_path / "cookie",
        log_path=tmp_path / "log.json",
        random_seed=1,
        paced=paced,
    )
    instance._last_url = "https://so.toutiao.com/search/?keyword=first"
    return instance


def test_search_fetcher_pacing_remains_enabled_by_default(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetcher_factory.time, "sleep", sleeps.append)
    instance = SearchFetcher(
        cookie_path=tmp_path / "cookie",
        log_path=tmp_path / "log.json",
        random_seed=1,
    )
    instance._last_url = "https://so.toutiao.com/search/?keyword=first"

    instance._pace()

    assert len(sleeps) == 1
    assert 4.0 <= sleeps[0] <= 8.0


def test_unpaced_search_fetcher_never_sleeps(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetcher_factory.time, "sleep", sleeps.append)
    instance = _fetcher(tmp_path, paced=False)

    for _ in range(8):
        instance._pace()

    assert sleeps == []


def test_stage_fallbacks_share_one_total_timeout_budget(tmp_path, monkeypatch):
    now = [0.0]
    attempts = []
    instance = _fetcher(tmp_path, paced=False)

    def fake_fetch_one(stage, _url, timeout):
        attempts.append((stage, timeout))
        now[0] += timeout
        return "", {"error": "timeout", "elapsed": timeout}

    monkeypatch.setattr(fetcher_factory.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(instance, "_fetch_one", fake_fetch_one)

    instance._fetch_with_active("https://so.toutiao.com/search/", 5)

    assert attempts == [(fetcher_factory.STAGE_URLLIB, 5)]


def test_referer_for_baidu_hosts():
    # News search host → news search referer (post-2026-07-21 switch from m.baidu.com).
    assert _referer_for("https://www.baidu.com/s?wd=test&tn=news") == "https://www.baidu.com/"
    # baijiahao article pages need a baidu referer (was m.baidu.com/s before the switch).
    assert _referer_for("https://baijiahao.baidu.com/s?id=123") == "https://www.baidu.com/s"
    # Board endpoint unchanged.
    assert _referer_for("https://top.baidu.com/api/board") == "https://top.baidu.com/"
    # Unknown hosts return None.
    assert _referer_for("https://example.com/foo") is None
