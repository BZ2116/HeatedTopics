from pathlib import Path

from heated_topics_v3.bilibili_cache import (
    get_or_fetch_search_with_record,
    get_or_fetch_article_with_record,
)


def test_search_layer_caches_then_hits(tmp_path: Path):
    calls = {"n": 0}

    def live(word: str) -> list:
        calls["n"] += 1
        return [{"cvid": "cv1", "title": "T"}]

    v1, s1 = get_or_fetch_search_with_record(tmp_path, "2026-07-22", "AI", live)
    v2, s2 = get_or_fetch_search_with_record(tmp_path, "2026-07-22", "AI", live)
    assert v1 == v2 == [{"cvid": "cv1", "title": "T"}]
    assert s1 == "fresh" and s2 == "cache"
    assert calls["n"] == 1


def test_article_force_refresh_rewrites(tmp_path: Path):
    def live(aid: str) -> dict:
        return {"content": "body", "fetch_status": "success"}

    _, s1 = get_or_fetch_article_with_record(tmp_path, "2026-07-22", "cv1", live)
    _, s2 = get_or_fetch_article_with_record(tmp_path, "2026-07-22", "cv1", live, force_refresh=True)
    assert s1 == "fresh" and s2 == "fresh"
