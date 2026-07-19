"""`--offline` must not touch the network — with or without a populated cache.

Two scenarios:

1. Empty cache + offline → the deadline (``time.monotonic()``) fires immediately
   inside ``_single_flight`` (after its ``load_cached()`` returns ``None``), so
   the pipeline returns empty markers and never invokes any fetcher. The report
   is the transparent "nothing found" fallback.
2. Populated cache + offline → ``_single_flight`` reads the cache BEFORE the
   deadline check, so pre-seeded board/search/article files flow through the
   pipeline unchanged. Still zero network calls.

Both scenarios patch ``urllib.request.urlopen`` and assert it is never called.
"""
import json
from datetime import date  # noqa: F401  (kept per plan; utc8_today drives cache dates)
from pathlib import Path
from unittest.mock import patch

import pytest

from heated_topics_v3.baidu_cache import _word_digest
from heated_topics_v3.hot_board_cache import utc8_today
from heated_topics_v3.pipeline import run_baidu_pipeline


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech"],
                "audience": ["devs"],
                "content_modes": ["tutorial"],
                "preferred_platforms": ["baidu"],
                "core_keywords": ["AI Agent"],
                "entity_keywords": [],
                "excluded_keywords": [],
            }
        ),
        encoding="utf-8",
    )
    return p


def test_offline_with_empty_cache_emits_zero_network_calls(
    tmp_path: Path, profile_path: Path
):
    blocked = {"calls": 0}

    def fail_urlopen(*a, **kw):  # pragma: no cover - asserts on invocation
        blocked["calls"] += 1
        raise AssertionError("offline mode must not call urlopen")

    with patch("urllib.request.urlopen", side_effect=fail_urlopen):
        outputs = run_baidu_pipeline(
            profile_path=profile_path,
            output_root=tmp_path / "outputs",
            fetched_at="2026-07-19T20:00:00+08:00",
            cache_root=tmp_path / "cache",
            offline=True,
        )

    assert blocked["calls"] == 0
    report = outputs["report"].read_text(encoding="utf-8")
    assert "本次未抓到任何条目" in report
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert hot_items == []


def test_offline_with_populated_cache_flows_data_without_network(
    tmp_path: Path, profile_path: Path
):
    today = utc8_today()
    cache_root = tmp_path / "cache"

    word = "AI Agent 发布"
    article_id = "1110000000000000001"
    article_url = f"https://baijiahao.baidu.com/s?id={article_id}"

    # ---- pre-populate the board cache ----
    # The pipeline re-parses the cached ``response_text`` with
    # ``parse_baidu_board_response``, so we seed the same JSON the live fetcher
    # would return. The hot word "AI Agent 发布" matches core_keyword "AI Agent".
    board_json = json.dumps(
        {
            "success": True,
            "data": {
                "cards": [
                    {
                        "component": "tabTextList",
                        "content": [
                            {
                                "content": [
                                    {
                                        "isTop": True,
                                        "word": word,
                                        "url": "https://m.baidu.com/s?word=AI-Agent",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    board_path = cache_root / "baidu" / "board" / f"{today}.json"
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(
        json.dumps(
            {"schema_version": 1, "date": today, "response_text": board_json},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ---- pre-populate the search cache (keyed by sha256(word)) ----
    search_path = (
        cache_root / "baidu" / "search" / today / f"{_word_digest(word)}.json"
    )
    search_path.parent.mkdir(parents=True, exist_ok=True)
    search_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "date": today,
                "word": word,
                "ids": [
                    {
                        "article_id": article_id,
                        "title": "AI Agent 实战",
                        "url": article_url,
                        "source_word": word,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ---- pre-populate the article cache (keyed by article_id) ----
    article_path = (
        cache_root / "baidu" / "articles" / today / f"{article_id}.json"
    )
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "date": today,
                "article_id": article_id,
                "title": word,
                "content": "正文内容",
                "extraction_method": "baijiahao_article_page",
                "fetch_status": "success",
                "html_length": 1000,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    blocked = {"calls": 0}

    def fail_urlopen(*a, **kw):  # pragma: no cover - asserts on invocation
        blocked["calls"] += 1
        raise AssertionError("offline mode must not call urlopen")

    with patch("urllib.request.urlopen", side_effect=fail_urlopen):
        outputs = run_baidu_pipeline(
            profile_path=profile_path,
            output_root=tmp_path / "outputs",
            fetched_at="2026-07-19T20:00:00+08:00",
            cache_root=cache_root,
            offline=True,
        )

    assert blocked["calls"] == 0

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert len(hot_items) == 1
    assert hot_items[0]["item"]["title"] == word
    assert hot_items[0]["detail"]["fetch_status"] == "success"
    assert hot_items[0]["detail"]["extraction_method"] == "baijiahao_article_page"

    text_files = sorted(outputs["article_texts"].glob("*.txt"))
    assert len(text_files) == 1

    report = outputs["report"].read_text(encoding="utf-8")
    assert "AI Agent" in report
