import time
from pathlib import Path

import pytest

from heated_topics_v3.baidu_cache import (
    get_or_fetch_board,
    get_or_fetch_board_with_record,
    get_or_fetch_search,
    get_or_fetch_search_with_record,
    get_or_fetch_article,
    get_or_fetch_article_with_record,
    _word_digest,
)


def test_board_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    fetched: list[str] = []

    def fetcher(date: str) -> dict:
        fetched.append(date)
        return {"raw": "<json>"}

    cache_root = tmp_path
    payload, src1 = get_or_fetch_board(cache_root, "2026-07-19", fetcher)
    assert payload == {"raw": "<json>"}
    assert src1 == "fresh"
    payload2, src2 = get_or_fetch_board(cache_root, "2026-07-19", fetcher)
    assert payload2 == payload
    assert src2 == "cache"
    assert len(fetched) == 1


def test_search_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fetcher returns a list; second call must yield the same list (not a dict)."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    fetched: list[str] = []

    def fetcher(word: str) -> list:
        fetched.append(word)
        return ["1", "2"]

    out, src1 = get_or_fetch_search(tmp_path, "2026-07-19", "携手", fetcher)
    assert out == ["1", "2"]
    assert src1 == "fresh"
    out2, src2 = get_or_fetch_search(tmp_path, "2026-07-19", "携手", fetcher)
    assert out2 == out
    assert isinstance(out2, list)
    assert src2 == "cache"
    assert len(fetched) == 1


def test_article_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    fetched: list[str] = []

    def fetcher(article_id: str) -> dict:
        fetched.append(article_id)
        return {"article_id": article_id, "chars": 123}

    out, src1 = get_or_fetch_article(tmp_path, "2026-07-19", "111", fetcher)
    assert src1 == "fresh"
    out2, src2 = get_or_fetch_article(tmp_path, "2026-07-19", "111", fetcher)
    assert src2 == "cache"
    assert len(fetched) == 1


def test_search_cache_lock_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If the lock is held beyond deadline, function returns empty list and 'lock_timeout'."""
    cache_path = tmp_path / "baidu" / "search" / "2026-07-19"
    cache_path.mkdir(parents=True, exist_ok=True)
    word = "abc"
    digest_sha = _word_digest(word)
    (cache_path / f"{digest_sha}.lock").write_text("held", encoding="utf-8")

    def fetcher(word: str) -> dict:  # pragma: no cover
        return {"word": word}

    out, src = get_or_fetch_search_with_record(
        tmp_path,
        "2026-07-19",
        word,
        fetcher,
        lock_wait_seconds=0.0,
        deadline=time.monotonic() + 0.05,
    )
    assert src == "lock_timeout"
    assert out == []

