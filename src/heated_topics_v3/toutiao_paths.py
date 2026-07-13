"""Four-path candidate builder for Toutiao.

Path A: Hot board priority (HotValue ≥ filters.hot_board_min, persona match)
Path B: Search by extracted keywords (article_heat > filters.article_heat_min)
Path C: is_toutiao_hot fallback (article_heat < 500 but is_toutiao_hot=true)
Path D: Optional LLM rerank of top-K candidates

Cross-path dedup by canonical URL; same item appearing in multiple paths
merges source_path (e.g. "A+B") and keeps the higher preliminary score.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from heated_topics_v3.contracts import ExtractedKeyword, HotItem
from heated_topics_v3.llm_client import LLMUnavailable, strip_code_fence
from heated_topics_v3.toutiao_scoring import (
    hybrid_score_v2,
)


PATH_A = "A"
PATH_B = "B"
PATH_C = "C"
PATH_D = "D"


@dataclass(frozen=True)
class Candidate:
    item: HotItem
    source_path: str
    matched_keyword: str | None = None
    is_toutiao_hot: bool = False
    is_hot_board: bool = False
    persona_matched: bool = False
    preliminary_score: float = 0.0


@dataclass(frozen=True)
class PathFilters:
    hot_board_min: int = 1_000_000
    article_heat_min: int = 1_000
    is_toutiao_hot_min_article_heat: int = 0
    is_toutiao_hot_max_article_heat: int = 500
    include_is_toutiao_hot_fallback: bool = True


def build_candidates(
    *,
    hot_board: list[HotItem],
    keywords: tuple[ExtractedKeyword, ...] = (),
    persona_keywords: tuple[str, ...] = (),
    search_results_by_keyword: dict[str, list[HotItem]] | None = None,
    article_info_by_url: dict[str, dict[str, Any]] | None = None,
    filters: PathFilters = PathFilters(),
) -> list[Candidate]:
    """Construct candidates from paths A/B/C, deduped, ready for scoring."""
    search_results_by_keyword = search_results_by_keyword or {}
    article_info_by_url = article_info_by_url or {}
    candidates_by_url: dict[str, Candidate] = {}

    # Path A — hot board priority
    for item in hot_board:
        scored = hybrid_score_v2(item, persona_keywords)
        if not scored.is_hot_board:
            continue
        if (item.heat.value or 0) < filters.hot_board_min:
            continue
        if persona_keywords and not scored.persona_matched:
            continue
        url = _canonical_url(item.url)
        candidate = Candidate(
            item=item,
            source_path=PATH_A,
            matched_keyword=item.summary or None,
            is_toutiao_hot=scored.is_toutiao_hot,
            is_hot_board=True,
            persona_matched=scored.persona_matched,
            preliminary_score=scored.score,
        )
        candidates_by_url[url] = candidate

    # Path B — search by extracted keywords (article_heat >= filters.article_heat_min)
    for extracted in keywords:
        phrase = extracted.keyword
        search_items = search_results_by_keyword.get(phrase, [])
        for item in search_items:
            url = _canonical_url(item.url)
            info = article_info_by_url.get(url)
            article_heat = _article_heat_from(info)
            if article_heat < filters.article_heat_min:
                continue
            is_th = bool(info and info.get("is_toutiao_hot"))
            scored = hybrid_score_v2(item, persona_keywords)
            candidate = Candidate(
                item=item,
                source_path=PATH_B,
                matched_keyword=phrase,
                is_toutiao_hot=is_th,
                is_hot_board=False,
                persona_matched=scored.persona_matched,
                preliminary_score=scored.score,
            )
            existing = candidates_by_url.get(url)
            if existing is None:
                candidates_by_url[url] = candidate
            else:
                candidates_by_url[url] = _merge_candidates(existing, candidate)

    # Path C — is_toutiao_hot fallback (article_heat < 500)
    if filters.include_is_toutiao_hot_fallback:
        for phrase, search_items in search_results_by_keyword.items():
            for item in search_items:
                url = _canonical_url(item.url)
                info = article_info_by_url.get(url)
                if not info or not info.get("is_toutiao_hot"):
                    continue
                article_heat = _article_heat_from(info)
                if not (filters.is_toutiao_hot_min_article_heat <= article_heat <= filters.is_toutiao_hot_max_article_heat):
                    continue
                scored = hybrid_score_v2(item, persona_keywords)
                candidate = Candidate(
                    item=item,
                    source_path=PATH_C,
                    matched_keyword=phrase,
                    is_toutiao_hot=True,
                    is_hot_board=False,
                    persona_matched=scored.persona_matched,
                    preliminary_score=scored.score,
                )
                existing = candidates_by_url.get(url)
                if existing is None:
                    candidates_by_url[url] = candidate
                else:
                    candidates_by_url[url] = _merge_candidates(existing, candidate)

    return list(candidates_by_url.values())


def _merge_candidates(a: Candidate, b: Candidate) -> Candidate:
    """Merge two candidates for the same URL: keep higher score, union source_path."""
    paths = sorted(set(a.source_path.split("+") + b.source_path.split("+")))
    primary = a if a.preliminary_score >= b.preliminary_score else b
    other = b if primary is a else a
    return Candidate(
        item=primary.item,
        source_path="+".join(paths),
        matched_keyword=primary.matched_keyword or other.matched_keyword,
        is_toutiao_hot=primary.is_toutiao_hot or other.is_toutiao_hot,
        is_hot_board=primary.is_hot_board or other.is_hot_board,
        persona_matched=primary.persona_matched or other.persona_matched,
        preliminary_score=primary.preliminary_score,
    )


def apply_llm_rerank(
    candidates: list[Candidate],
    *,
    llm: Callable[..., str],
    top_n_for_rerank: int = 30,
    persona_keywords: tuple[str, ...] = (),
    body_excerpts: dict[str, str] | None = None,
) -> list[Candidate]:
    """Reorder the top-K candidates via LLM. Returns reordered list (input on failure)."""
    if len(candidates) <= 1:
        return candidates

    sorted_candidates = sorted(
        candidates,
        key=lambda c: (-c.preliminary_score, 0 if c.is_toutiao_hot else 1),
    )
    rerank_pool = sorted_candidates[: max(1, top_n_for_rerank)]
    body_excerpts = body_excerpts or {}

    system = (
        "你是中文内容排序助手。对给定候选文章列表，按 persona 相关性和热度综合排序。"
        "严格输出 JSON 数组，每项 {\"index\": <0-based 原列表 index>, \"final_rank\": <1-based 新位置>}。"
        "不要额外解释。"
    )
    payload = {
        "persona_keywords": list(persona_keywords),
        "candidates": [
            {
                "index": i,
                "title": c.item.title,
                "url": c.item.url,
                "preliminary_score": round(c.preliminary_score, 3),
                "source_path": c.source_path,
                "is_toutiao_hot": c.is_toutiao_hot,
                "excerpt": body_excerpts.get(_canonical_url(c.item.url), "")[:400],
            }
            for i, c in enumerate(rerank_pool)
        ],
    }
    try:
        raw = llm(
            json.dumps(payload, ensure_ascii=False, indent=2),
            system=system,
            max_tokens=2048,
            temperature=0.2,
        )
    except LLMUnavailable:
        return candidates

    cleaned = strip_code_fence(raw)
    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    if not match:
        return candidates
    try:
        order = json.loads(match.group(0))
    except json.JSONDecodeError:
        return candidates
    if not isinstance(order, list) or not order:
        return candidates

    new_positions: dict[int, int] = {}
    for entry in order:
        if not isinstance(entry, dict):
            continue
        try:
            idx = int(entry["index"])
            rank = int(entry["final_rank"])
        except (KeyError, TypeError, ValueError):
            continue
        new_positions[idx] = rank

    def rerank_key(c: Candidate) -> tuple[int, int]:
        idx = rerank_pool.index(c) if c in rerank_pool else len(rerank_pool)
        new_rank = new_positions.get(idx, idx + 1)
        return (new_rank, 0 if c.is_toutiao_hot else 1)

    reranked = sorted(rerank_pool, key=rerank_key)
    leftover = [c for c in sorted_candidates if c not in rerank_pool]
    return reranked + leftover


def _canonical_url(url: str) -> str:
    # Strip query string; preserve trailing slash so callers can match exactly.
    return url.split("?", maxsplit=1)[0]


def _article_heat_from(info: dict[str, Any] | None) -> int:
    if not info:
        return 0
    value = info.get("article_heat")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0