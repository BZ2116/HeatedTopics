"""Hybrid scoring for Toutiao candidates.

Unifies HotValue (1.5K-21M) and article_heat (0-50K) on a log10 scale.
Hot board items get a +1.5 boost; search items get a +3.0 base offset so they
remain comparable to hot board items. Optional is_toutiao_hot (+0.5) and
persona_match (+0.3) boosts apply on top.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from heated_topics_v3.contracts import HotItem


IS_TOUTIAO_HOT_BOOST = 0.5
PERSONA_MATCH_BOOST = 0.3
SEARCH_BASE_OFFSET = 3.0
HOT_BOARD_BASE_BOOST = 1.5
DEFAULT_HOT_BOARD_RANK = 9999


@dataclass(frozen=True)
class ScoredCandidate:
    item: HotItem
    score: float
    is_toutiao_hot: bool
    is_hot_board: bool
    hot_board_rank: int
    persona_matched: bool


def hybrid_score_v2(item: HotItem, persona_keywords: tuple[str, ...] = ()) -> ScoredCandidate:
    is_hot_board = bool(item.raw_payload.get("source_kind") in {"hot_board", "search_hot_board_overlap"})
    is_toutiao_hot = bool(item.raw_payload.get("is_toutiao_hot"))
    hot_value = int(item.heat.value or 0) if is_hot_board else 0
    article_heat = int(item.raw_payload.get("article_heat") or 0) if not is_hot_board else 0

    if is_hot_board:
        base = math.log10(max(hot_value, 0) + 1) + HOT_BOARD_BASE_BOOST
    else:
        base = math.log10(max(article_heat, 0) + 1) + SEARCH_BASE_OFFSET

    boost = 0.0
    if is_toutiao_hot:
        boost += IS_TOUTIAO_HOT_BOOST
    persona_matched = _persona_matches(item, persona_keywords)
    if persona_matched:
        boost += PERSONA_MATCH_BOOST

    score = base + boost
    rank = int(item.rank) if is_hot_board and item.rank is not None else DEFAULT_HOT_BOARD_RANK

    return ScoredCandidate(
        item=item,
        score=score,
        is_toutiao_hot=is_toutiao_hot,
        is_hot_board=is_hot_board,
        hot_board_rank=rank,
        persona_matched=persona_matched,
    )


def as_sort_key(scored: ScoredCandidate) -> tuple[float, int, int]:
    """Sort by (-score desc, -is_toutiao_hot desc, hot_board_rank asc)."""
    return (
        -scored.score,
        0 if scored.is_toutiao_hot else 1,
        scored.hot_board_rank,
    )


def _persona_matches(item: HotItem, persona_keywords: tuple[str, ...]) -> bool:
    if not persona_keywords:
        return False
    haystack = _searchable_text(item)
    for keyword in persona_keywords:
        if keyword and keyword.casefold() in haystack:
            return True
    return False


def _searchable_text(item: HotItem) -> str:
    bits: list[str] = [item.title, item.summary, item.category]
    for value in item.raw_payload.values():
        if isinstance(value, str):
            bits.append(value)
        elif isinstance(value, dict):
            bits.extend(str(child) for child in value.values() if isinstance(child, str))
    return " ".join(bits).casefold()