"""Tests for embedding-based relevance scoring (v2.1.2)."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock

import pytest

from heated_topics_v3.openbiliclaw_integration import relevance


def test_heat_factor_rank_1_is_1() -> None:
    assert relevance._heat_factor_from_rank(1) == 1.0


def test_heat_factor_rank_2_is_0_5() -> None:
    assert relevance._heat_factor_from_rank(2) == 0.5


def test_heat_factor_rank_30_floors_at_0_05() -> None:
    """rank 30 → 1/30 ≈ 0.033, which is below the 0.05 floor → clamped."""
    assert relevance._heat_factor_from_rank(30) == 0.05


def test_heat_factor_rank_200_floors_at_0_05() -> None:
    """Below 0.05 the heat signal is noise; clamp to floor."""
    assert relevance._heat_factor_from_rank(200) == 0.05


def test_heat_factor_rank_0_floors_at_0_05() -> None:
    assert relevance._heat_factor_from_rank(0) == 0.05


def test_heat_factor_negative_floors_at_0_05() -> None:
    assert relevance._heat_factor_from_rank(-5) == 0.05


# --- score_article ---


def _unit_vec(*coords: float) -> list[float]:
    """Build a unit vector from coords (for deterministic cosine tests)."""
    norm = math.sqrt(sum(c * c for c in coords))
    if norm == 0:
        return [0.0 for _ in coords]
    return [c / norm for c in coords]


def test_score_article_returns_none_below_threshold() -> None:
    """Off-topic article (sim 0 < 0.5) is pre-filtered."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [_unit_vec(0.0, 1.0, 0.0), _unit_vec(0.0, 0.0, 1.0)]
    assert relevance.score_article(article, kws, rank=1, threshold=0.5) is None


def test_score_article_returns_sim_times_heat_factor() -> None:
    """On-topic article at rank 2 (heat 0.5) with sim 1.0 → 0.5."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [_unit_vec(1.0, 0.0, 0.0)]
    score = relevance.score_article(article, kws, rank=2, threshold=0.5)
    assert score == pytest.approx(0.5, rel=1e-3)


def test_score_article_uses_max_sim_across_keywords() -> None:
    """Take the best-matching keyword, not the average."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [
        _unit_vec(0.0, 1.0, 0.0),  # orthogonal → sim 0
        _unit_vec(1.0, 0.0, 0.0),  # identical → sim 1
    ]
    score = relevance.score_article(article, kws, rank=10, threshold=0.5)
    assert score == pytest.approx(1 / 10, rel=1e-3)


def test_score_article_heat_floors_at_0_05_for_very_low_rank() -> None:
    """rank 1000 → heat 0.001 floored to 0.05; sim 1.0 → 0.05."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [_unit_vec(1.0, 0.0, 0.0)]
    score = relevance.score_article(article, kws, rank=1000, threshold=0.5)
    assert score == pytest.approx(0.05, rel=1e-3)


def test_score_article_returns_none_when_no_keywords() -> None:
    """No keywords → no embedding match → always pre-filtered."""
    article = _unit_vec(1.0, 0.0, 0.0)
    assert relevance.score_article(article, [], rank=1, threshold=0.5) is None


def test_score_article_handles_zero_vector_article() -> None:
    """Degenerate embedding (all zeros) → no sim → pre-filtered."""
    kws = [_unit_vec(1.0, 0.0, 0.0)]
    assert relevance.score_article([0.0, 0.0, 0.0], kws, rank=1, threshold=0.5) is None


def test_score_article_handles_zero_vector_keyword() -> None:
    """Zero-vector keyword contributes 0 sim; other keywords still count."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [[0.0, 0.0, 0.0], _unit_vec(1.0, 0.0, 0.0)]
    score = relevance.score_article(article, kws, rank=10, threshold=0.5)
    assert score == pytest.approx(1 / 10, rel=1e-3)


# --- embed_keywords ---


@pytest.mark.asyncio
async def test_embed_keywords_calls_embed_for_each_keyword() -> None:
    """Each keyword is embedded once; order preserved."""
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    vecs = await relevance.embed_keywords(["非遗", "节气", "民俗"], fake_emb)
    assert vecs == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert fake_emb.embed.call_count == 3


@pytest.mark.asyncio
async def test_embed_keywords_empty_list_returns_empty() -> None:
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock()
    vecs = await relevance.embed_keywords([], fake_emb)
    assert vecs == []
    fake_emb.embed.assert_not_called()


@pytest.mark.asyncio
async def test_embed_keywords_skips_empty_embedding_results() -> None:
    """If embed returns [] (e.g. provider failure), drop that keyword."""
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[
        [1.0, 0.0],  # non-empty
        [],          # empty → drop
        [0.0, 1.0],  # non-empty
    ])
    vecs = await relevance.embed_keywords(["a", "b", "c"], fake_emb)
    assert vecs == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.asyncio
async def test_embed_keywords_returns_empty_when_all_fail() -> None:
    """All keywords embedding failed → empty list → caller falls back to 1/rank."""
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[[], [], []])
    vecs = await relevance.embed_keywords(["a", "b", "c"], fake_emb)
    assert vecs == []


@pytest.mark.asyncio
async def test_embed_keywords_swallows_per_call_exceptions() -> None:
    """One keyword fails → skip it; others continue."""
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[
        [1.0, 0.0],
        RuntimeError("ollama timeout"),
        [0.0, 1.0],
    ])
    vecs = await relevance.embed_keywords(["a", "b", "c"], fake_emb)
    assert vecs == [[1.0, 0.0], [0.0, 1.0]]


# --- v2.1.4: view-based heat factor + heat_source switch ---


def test_heat_factor_from_view_zero_floors() -> None:
    """Missing view_count → floor (no signal)."""
    assert relevance._heat_factor_from_view(0) == 0.05


def test_heat_factor_from_view_negative_floors() -> None:
    assert relevance._heat_factor_from_view(-100) == 0.05


def test_heat_factor_from_view_saturates_at_100k() -> None:
    """view_count ≥ 100k saturates at ~1.0."""
    assert relevance._heat_factor_from_view(100_000) == pytest.approx(1.0, abs=1e-3)
    assert relevance._heat_factor_from_view(1_000_000) == 1.0


def test_heat_factor_from_view_mid_range_log_scaled() -> None:
    """100 views → ~0.4, 1000 views → ~0.6, 10000 → ~0.8 (log-scaled)."""
    assert relevance._heat_factor_from_view(100) == pytest.approx(0.40, abs=0.02)
    assert relevance._heat_factor_from_view(1_000) == pytest.approx(0.60, abs=0.02)
    assert relevance._heat_factor_from_view(10_000) == pytest.approx(0.80, abs=0.02)


def test_heat_factor_switch_uses_rank_by_default() -> None:
    """heat_source='rank' (default) → 1/rank behavior regardless of view."""
    assert relevance.heat_factor(rank=2, view_count=1_000_000) == 0.5


def test_heat_factor_switch_uses_view_when_requested() -> None:
    """heat_source='view' with view_count > 0 → log(view+1)/log(100001)."""
    val = relevance.heat_factor(
        rank=2, view_count=1_000_000, source="view",
    )
    # 1M views saturates to 1.0, beats rank-based 0.5
    assert val == pytest.approx(1.0, abs=1e-3)


def test_heat_factor_switch_view_falls_back_to_rank_on_zero() -> None:
    """heat_source='view' with view_count=0 → rank-based fallback."""
    assert relevance.heat_factor(
        rank=10, view_count=0, source="view",
    ) == pytest.approx(0.1, abs=1e-3)


def test_score_article_uses_view_heat_when_requested() -> None:
    """score_article passes view_count + heat_source into the heat factor."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [_unit_vec(1.0, 0.0, 0.0)]
    # sim 1.0 * heat_factor(view=100000, source=view) = 1.0 * 1.0 = 1.0
    score = relevance.score_article(
        article, kws, rank=100, view_count=100_000,
        threshold=0.5, heat_source="view",
    )
    assert score == pytest.approx(1.0, abs=1e-3)


def test_score_article_default_heat_source_is_rank() -> None:
    """Backward compat: omitting heat_source keeps 1/rank behavior."""
    article = _unit_vec(1.0, 0.0, 0.0)
    kws = [_unit_vec(1.0, 0.0, 0.0)]
    # sim 1.0 * heat_factor(rank=20) = 0.05 (rank 20 → 1/20 = 0.05, at floor)
    score = relevance.score_article(article, kws, rank=20, threshold=0.5)
    assert score == pytest.approx(0.05, abs=1e-3)
