from pathlib import Path

from heated_topics_v3.juejin_cache import (
    get_or_fetch_board_with_record,
    get_or_fetch_search_with_record,
    get_or_fetch_article_with_record,
)


def test_board_layer_date_key(tmp_path: Path):
    v, s = get_or_fetch_board_with_record(tmp_path, "2026-07-22", lambda d: {"response_text": "x"})
    assert v == {"response_text": "x"} and s == "fresh"
    _, s2 = get_or_fetch_board_with_record(tmp_path, "2026-07-22", lambda d: {"response_text": "y"})
    assert s2 == "cache"


def test_search_and_article_layers(tmp_path: Path):
    _, s1 = get_or_fetch_search_with_record(tmp_path, "2026-07-22", "AI", lambda w: [{"id": "1"}])
    _, s2 = get_or_fetch_article_with_record(tmp_path, "2026-07-22", "1", lambda a: {"content": "c"})
    assert s1 == "fresh" and s2 == "fresh"
