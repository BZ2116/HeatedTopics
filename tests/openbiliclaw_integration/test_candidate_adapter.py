"""Tests for candidate_adapter module."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from heated_topics_v3.openbiliclaw_integration import candidate_adapter


def asyncio_run(coro):
    """Run a coroutine in a fresh loop. Used by sync tests calling async
    to_discovered without pytest-asyncio decoration."""
    return asyncio.new_event_loop().run_until_complete(coro)


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
    items = asyncio_run(candidate_adapter.to_discovered(juejin_articles, platform="juejin"))
    assert len(items) == 5
    first = items[0]
    assert first.title == "用 Tokio 实现零信任网关：源码级拆解"
    assert first.content_url == "https://juejin.cn/post/712345"
    assert first.source_platform == "juejin"
    assert first.content_id == "712345"
    assert first.content_type == "note"


def test_to_discovered_maps_heat_fields(juejin_articles: list[dict]) -> None:
    items = asyncio_run(candidate_adapter.to_discovered(juejin_articles, platform="juejin"))
    first = items[0]
    assert first.view_count == 12345
    assert first.like_count == 234
    assert first.comment_count == 56
    assert first.source_rank == 3


def test_to_discovered_includes_body_text(juejin_articles: list[dict]) -> None:
    items = asyncio_run(candidate_adapter.to_discovered(juejin_articles, platform="juejin"))
    assert "Tokio" in items[0].body_text
    assert "零信任" in items[0].body_text


def test_to_discovered_uses_platform_namespaced_item_key(
    juejin_articles: list[dict],
) -> None:
    items = asyncio_run(candidate_adapter.to_discovered(juejin_articles, platform="juejin"))
    assert items[0].item_key.startswith("juejin:")
    assert "712345" in items[0].item_key


def test_to_discovered_for_zhihu(zhihu_articles: list[dict]) -> None:
    items = asyncio_run(candidate_adapter.to_discovered(zhihu_articles, platform="zhihu"))
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
    items = asyncio_run(candidate_adapter.to_discovered(bad, platform="juejin"))
    assert len(items) == 1
    assert items[0].content_id == "1"


def test_to_discovered_preserves_tags(juejin_articles: list[dict]) -> None:
    items = asyncio_run(candidate_adapter.to_discovered(juejin_articles, platform="juejin"))
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
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="juejin"))
    assert items[0].view_count == 0
    assert items[0].like_count == 0


def test_to_discovered_maps_rank_to_relevance_score(juejin_articles: list[dict]) -> None:
    """rank 1 -> 1.0, rank 2 -> 0.5, rank 5 -> 0.2. Ensures confidence field
    on returned Recommendations is non-zero. Mirrors the OpenBiliClaw
    relevance_score floor (0.01) so the engine never sees a zero score.
    """
    items = asyncio_run(candidate_adapter.to_discovered(juejin_articles, platform="juejin"))
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
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="juejin"))
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
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="juejin"))
    assert items[0].relevance_score == pytest.approx(0.01)


def test_to_discovered_uses_per_article_platform_when_present() -> None:
    """When an article carries its own ``platform`` (set by the provider
    fetcher in ``_hotitem_to_article``), use it. Fall back to the function
    arg only when missing. Regression: previously all articles inherited
    the first article's platform, collapsing toutiao/zhihu/bilibili into
    one source and making MMR diversity blind to actual content mix.
    """
    articles = [
        {
            "article_id": "1",
            "title": "toutiao item",
            "url": "https://t.com/1",
            "body_text": "x",
            "platform": "toutiao",
        },
        {
            "article_id": "2",
            "title": "bilibili item",
            "url": "https://b.com/2",
            "body_text": "x",
            "platform": "dailyhot:bilibili",
        },
        {
            "article_id": "3",
            "title": "no platform key",
            "url": "https://x.com/3",
            "body_text": "x",
        },
    ]
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="toutiao"))
    by_id = {item.content_id: item for item in items}
    assert by_id["1"].source_platform == "toutiao"
    assert by_id["2"].source_platform == "dailyhot:bilibili"
    # Item 3 has no platform key — should fall back to the arg.
    assert by_id["3"].source_platform == "toutiao"


# --- v2.1.2: embedding-based relevance + pre-filter ---


@pytest.mark.asyncio
async def test_to_discovered_filters_below_sim_threshold() -> None:
    """Off-topic article (sim 0) is pre-filtered; on-topic (sim 1.0) kept."""
    articles = [
        {
            "article_id": "off", "title": "Flutter UI 技巧",
            "url": "https://x/1", "body_text": "技术内容",
            "heat": {"rank": 1},
        },
        {
            "article_id": "on", "title": "非遗手工艺传承",
            "url": "https://x/2", "body_text": "传统工艺",
            "heat": {"rank": 5},
        },
    ]
    # Keyword vec = [1, 0, 0]. Article 1 (Flutter) → orthogonal → sim 0.
    # Article 2 (非遗) → identical → sim 1.0.
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[
        [0.0, 1.0, 0.0],  # "Flutter UI 技巧 | 技术内容" — orthogonal → sim 0
        [1.0, 0.0, 0.0],  # "非遗手工艺传承 | 传统工艺" — identical → sim 1.0
    ])
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
        embedding_service=fake_emb,
        keyword_vectors=[[1.0, 0.0, 0.0]],
        sim_threshold=0.5,
    )
    assert [it.content_id for it in items] == ["on"]
    assert items[0].relevance_score == pytest.approx(1.0 * (1 / 5), rel=1e-3)


@pytest.mark.asyncio
async def test_to_discovered_without_keyword_vectors_falls_back_to_rank() -> None:
    """Backward compat: no vectors → 1/rank behavior (v2.1.1)."""
    articles = [
        {
            "article_id": "1", "title": "anything",
            "url": "https://x/1", "body_text": "x",
            "heat": {"rank": 10},
        },
    ]
    items = await candidate_adapter.to_discovered(articles, platform="juejin")
    assert items[0].relevance_score == pytest.approx(1 / 10, rel=1e-3)


@pytest.mark.asyncio
async def test_to_discovered_uses_empty_keyword_vecs_as_fallback() -> None:
    """Empty keyword_vectors → can't compute sim → fall back to 1/rank."""
    articles = [
        {
            "article_id": "1", "title": "x", "url": "https://x/1",
            "body_text": "x", "heat": {"rank": 4},
        },
    ]
    fake_emb = AsyncMock()
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
        embedding_service=fake_emb, keyword_vectors=[], sim_threshold=0.5,
    )
    assert items[0].relevance_score == pytest.approx(1 / 4, rel=1e-3)
    # Embed was never called because we have no keyword vectors to compare to.
    fake_emb.embed.assert_not_called()


@pytest.mark.asyncio
async def test_to_discovered_skips_article_when_embed_returns_empty() -> None:
    """If embed returns [] for the article, treat as no-signal → skip (pre-filter)."""
    articles = [
        {
            "article_id": "1", "title": "x", "url": "https://x/1",
            "body_text": "x", "heat": {"rank": 1},
        },
    ]
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(return_value=[])  # provider failure
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
        embedding_service=fake_emb,
        keyword_vectors=[[1.0, 0.0, 0.0]],
        sim_threshold=0.5,
    )
    assert items == []


# --- v2.1.4: min_view_count hard filter + heat_source=view ---


@pytest.mark.asyncio
async def test_to_discovered_min_view_count_drops_low_engagement() -> None:
    """min_view_count=1000 drops view_count=500, keeps view_count=5000."""
    articles = [
        {
            "article_id": "low", "title": "低热度", "url": "https://x/1",
            "body_text": "x", "heat": {"rank": 1, "view": 500},
        },
        {
            "article_id": "high", "title": "高热度", "url": "https://x/2",
            "body_text": "x", "heat": {"rank": 2, "view": 5_000},
        },
    ]
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[
        [1.0, 0.0, 0.0],  # low: identical to kw
        [1.0, 0.0, 0.0],  # high: identical to kw
    ])
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
        embedding_service=fake_emb,
        keyword_vectors=[[1.0, 0.0, 0.0]],
        sim_threshold=0.5,
        min_view_count=1000,
    )
    assert [it.content_id for it in items] == ["high"]


@pytest.mark.asyncio
async def test_to_discovered_min_view_count_default_zero_no_filter() -> None:
    """min_view_count=0 (default) keeps all candidates regardless of view."""
    articles = [
        {
            "article_id": "zero", "title": "零阅读", "url": "https://x/1",
            "body_text": "x", "heat": {"rank": 1, "view": 0},
        },
    ]
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
    )
    assert len(items) == 1
    assert items[0].view_count == 0


@pytest.mark.asyncio
async def test_to_discovered_heat_source_view_uses_log_view() -> None:
    """heat_source='view' swaps 1/rank for log(view+1)/log(100001)."""
    # rank 1 → rank-based heat = 1.0; view 100k → view-based heat = 1.0 too.
    # Difference shows up at rank 100 with view_count=100k:
    #   rank-based: heat = 0.05 (floor)
    #   view-based: heat = 1.0 (saturated)
    articles = [
        {
            "article_id": "1", "title": "x", "url": "https://x/1",
            "body_text": "x", "heat": {"rank": 100, "view": 100_000},
        },
    ]
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
        embedding_service=fake_emb,
        keyword_vectors=[[1.0, 0.0, 0.0]],
        sim_threshold=0.5,
        heat_source="view",
    )
    assert items[0].relevance_score == pytest.approx(1.0, abs=1e-2)


@pytest.mark.asyncio
async def test_to_discovered_heat_source_view_falls_back_when_no_view() -> None:
    """heat_source='view' with view_count=0 → rank-based fallback."""
    articles = [
        {
            "article_id": "1", "title": "x", "url": "https://x/1",
            "body_text": "x", "heat": {"rank": 4, "view": 0},
        },
    ]
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])
    items = await candidate_adapter.to_discovered(
        articles, platform="juejin",
        embedding_service=fake_emb,
        keyword_vectors=[[1.0, 0.0, 0.0]],
        sim_threshold=0.5,
        heat_source="view",
    )
    # rank 4 → 1/4 = 0.25
    assert items[0].relevance_score == pytest.approx(0.25, abs=1e-3)


# --- v2.1.6: source-level filter (video / login-gated platforms) ----------


def test_to_discovered_drops_unusable_sources() -> None:
    """douyin / xiaohongshu items are dropped before embedding.

    Acts as a safety net for the driver-level platforms list — if a caller
    accidentally includes these via `provider=` overrides or per-platform
    config, they still won't reach the engine.
    """
    articles = [
        {
            "article_id": "weibo:1", "title": "wb", "url": "https://w.com/1",
            "body_text": "x", "platform": "weibo", "heat": {"rank": 1},
        },
        {
            "article_id": "bili:1", "title": "bl", "url": "https://b.com/1",
            "body_text": "x", "platform": "bilibili", "heat": {"rank": 1},
        },
        {
            "article_id": "dy:1", "title": "dy", "url": "https://d.com/1",
            "body_text": "x", "platform": "douyin", "heat": {"rank": 1},
        },
        {
            "article_id": "xhs:1", "title": "xhs", "url": "https://x.com/1",
            "body_text": "x", "platform": "xiaohongshu", "heat": {"rank": 1},
        },
        {
            "article_id": "zhihu:1", "title": "zh", "url": "https://z.com/1",
            "body_text": "x", "platform": "zhihu", "heat": {"rank": 1},
        },
    ]
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="weibo"))
    ids = {item.content_id for item in items}
    assert "weibo:1" in ids
    assert "zhihu:1" in ids
    assert "bili:1" in ids
    assert "dy:1" not in ids
    assert "xhs:1" not in ids


def test_to_discovered_allows_bilibili_platform_kwarg() -> None:
    """Bilibili is a supported last30days reference source."""
    articles = [
        {
            "article_id": "1", "title": "t", "url": "https://x.com/1",
            "body_text": "x", "heat": {"rank": 1},
        },
    ]
    items = asyncio_run(
        candidate_adapter.to_discovered(articles, platform="bilibili")
    )
    assert [item.content_id for item in items] == ["1"]


def test_blocked_sources_constant_covers_video_platforms() -> None:
    """Sanity check on the module-level constant — guards against typos
    that would silently re-enable blocked platforms."""
    assert "bilibili" not in candidate_adapter.BLOCKED_SOURCES
    assert "douyin" in candidate_adapter.BLOCKED_SOURCES
    assert "xiaohongshu" in candidate_adapter.BLOCKED_SOURCES
    # Article sources must NOT be in the block set.
    assert "weibo" not in candidate_adapter.BLOCKED_SOURCES
    assert "zhihu" not in candidate_adapter.BLOCKED_SOURCES
    assert "juejin" not in candidate_adapter.BLOCKED_SOURCES


def test_to_discovered_drops_resource_and_discussion_posts() -> None:
    articles = [
        {"article_id": "resource", "title": "AI 资料分享和网盘链接", "url": "https://x/1", "body_text": "正文", "heat": {"rank": 1}},
        {"article_id": "discussion", "title": "大家怎么看这个 AI 话题讨论", "url": "https://x/2", "body_text": "正文", "heat": {"rank": 2}},
        {"article_id": "article", "title": "AI 推理性能优化实践", "url": "https://x/3", "body_text": "正文", "heat": {"rank": 3}},
    ]
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="weibo"))
    assert [item.content_id for item in items] == ["article"]


def test_to_discovered_keeps_weak_reference_with_lower_score() -> None:
    articles = [
        {
            "article_id": "weak", "title": "非遗短内容",
            "url": "https://x/weak", "body_text": "这是一段很短的内容说明",
            "heat": {"rank": 1},
        },
        {
            "article_id": "strong", "title": "非遗传承实践分析",
            "url": "https://x/strong",
            "body_text": "第一段介绍背景和问题。\n第二段分析传承方法与生活场景。\n第三段总结实践经验。",
            "heat": {"rank": 1},
        },
    ]
    items = asyncio_run(candidate_adapter.to_discovered(articles, platform="weibo"))
    by_id = {item.content_id: item for item in items}
    assert set(by_id) == {"weak", "strong"}
    assert by_id["weak"].relevance_score < by_id["strong"].relevance_score
