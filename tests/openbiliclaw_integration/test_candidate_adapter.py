"""Tests for candidate_adapter module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from heated_topics_v3.openbiliclaw_integration import candidate_adapter


@pytest.fixture
def juejin_articles(fixtures_dir: Path) -> list[dict[str, Any]]:
    return json.loads(
        (fixtures_dir / "articles_juejin_5.json").read_text(encoding="utf-8")
    )["articles"]


@pytest.fixture
def zhihu_articles(fixtures_dir: Path) -> list[dict[str, Any]]:
    return json.loads(
        (fixtures_dir / "articles_zhihu_3.json").read_text(encoding="utf-8")
    )["articles"]


def test_to_discovered_maps_basic_fields(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert len(items) == 5
    first = items[0]
    assert first.title == "用 Tokio 实现零信任网关：源码级拆解"
    assert first.content_url == "https://juejin.cn/post/712345"
    assert first.source_platform == "juejin"
    assert first.content_id == "712345"
    assert first.content_type == "note"


def test_to_discovered_maps_heat_fields(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    first = items[0]
    assert first.view_count == 12345
    assert first.like_count == 234
    assert first.comment_count == 56
    assert first.source_rank == 3


def test_to_discovered_includes_body_text(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert "Tokio" in items[0].body_text
    assert "零信任" in items[0].body_text


def test_to_discovered_uses_platform_namespaced_item_key(
    juejin_articles: list[dict],
) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert items[0].item_key.startswith("juejin:")
    assert "712345" in items[0].item_key


def test_to_discovered_for_zhihu(zhihu_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(zhihu_articles, platform="zhihu")
    assert len(items) == 3
    assert items[0].content_id == "q_987654"
    assert items[0].source_platform == "zhihu"
    assert items[0].item_key.startswith("zhihu:")


def test_to_discovered_skips_articles_missing_required_fields() -> None:
    bad = [
        {"article_id": "1", "title": "ok", "url": "https://x.com/1", "body_text": "x"},
        {"title": "no id", "url": "https://x.com/2", "body_text": "x"},
        {"article_id": "3", "url": "https://x.com/3", "body_text": "x"},
        {"article_id": "4", "title": "no url", "body_text": "x"},
    ]
    items = candidate_adapter.to_discovered(bad, platform="juejin")
    assert len(items) == 1
    assert items[0].content_id == "1"


def test_to_discovered_preserves_tags(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert "Rust" in items[0].tags
    assert "Tokio" in items[0].tags


def test_to_discovered_handles_missing_heat_field() -> None:
    articles = [
        {
            "article_id": "1",
            "title": "no heat",
            "url": "https://x.com/1",
            "body_text": "x",
        }
    ]
    items = candidate_adapter.to_discovered(articles, platform="juejin")
    assert items[0].view_count == 0
    assert items[0].like_count == 0


def test_to_discovered_maps_rank_to_relevance_score(juejin_articles: list[dict]) -> None:
    """rank 1 -> 1.0, rank 2 -> 0.5, rank 5 -> 0.2. Ensures confidence field
    on returned Recommendations is non-zero. Mirrors the OpenBiliClaw
    relevance_score floor (0.01) so the engine never sees a zero score.
    """
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    by_rank = {item.source_rank: item for item in items}
    assert by_rank[1].relevance_score == pytest.approx(1.0)
    assert by_rank[3].relevance_score == pytest.approx(1.0 / 3)
    assert by_rank[5].relevance_score == pytest.approx(0.2)
    assert by_rank[8].relevance_score == pytest.approx(0.125)


def test_to_discovered_relevance_score_floor_on_missing_rank() -> None:
    articles = [
        {
            "article_id": "1",
            "title": "no rank",
            "url": "https://x.com/1",
            "body_text": "x",
        }
    ]
    items = candidate_adapter.to_discovered(articles, platform="juejin")
    assert items[0].relevance_score == pytest.approx(0.01)


def test_to_discovered_relevance_score_floor_on_zero_rank() -> None:
    articles = [
        {
            "article_id": "1",
            "title": "rank zero",
            "url": "https://x.com/1",
            "body_text": "x",
            "heat": {"rank": 0},
        }
    ]
    items = candidate_adapter.to_discovered(articles, platform="juejin")
    assert items[0].relevance_score == pytest.approx(0.01)
