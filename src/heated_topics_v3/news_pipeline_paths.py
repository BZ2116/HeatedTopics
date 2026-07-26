"""Platform-agnostic Path A/B/C candidate builder.

Each news platform (Toutiao, Sina, NetEase, ...) supplies three callables via
``NewsPathContext``:
    - ``identity_key(item)``         — dedup key for the platform
    - ``enrich_with_article_info``   — attach article-info fields to an item
    - ``score_item(item, persona)``  — (score, persona_matched, is_toutiao_hot) for an item

The shared builder handles Path A (hot board) → B (per-keyword search) → C
(is_toutiao_hot fallback) merging and dedup by ``identity_key``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from heated_topics_v3.contracts import ExtractedKeyword, HotItem

if TYPE_CHECKING:
    # Imported lazily to avoid circular import with toutiao_paths.
    from heated_topics_v3.toutiao_paths import Candidate, PathFilters


PATH_A = "A"
PATH_B = "B"
PATH_C = "C"


@dataclass(frozen=True)
class NewsScore:
    score: float
    persona_matched: bool
    is_toutiao_hot: bool = False


@dataclass(frozen=True)
class NewsPathContext:
    """Platform-specific hooks for the shared Path A/B/C builder."""

    identity_key: Callable[[HotItem], str]
    enrich_with_article_info: Callable[[HotItem, dict[str, Any] | None], HotItem]
    score_item: Callable[[HotItem, tuple[str, ...]], NewsScore]


def build_news_candidates(
    *,
    hot_board: list[HotItem],
    keywords: tuple[ExtractedKeyword, ...],
    persona_keywords: tuple[str, ...],
    search_results_by_keyword: dict[str, list[HotItem]],
    article_info_by_key: dict[str, dict[str, Any]],
    filters: "PathFilters",
    ctx: NewsPathContext,
) -> list["Candidate"]:
    """Path A → B (article_heat >= filters.article_heat_min) → C (is_toutiao_hot fallback).

    Deduped by ``ctx.identity_key``. Short-circuits Path B/C if Path A already
    yields >= ``filters.min_hot_board_before_search`` hot board candidates.
    """
    from heated_topics_v3.toutiao_paths import Candidate as _Candidate
    out: dict[str, Candidate] = {}

    # Path A: hot board candidates passing hot_board_min + persona filter
    for item in hot_board:
        heat_value = item.heat.value or 0
        if heat_value < filters.hot_board_min:
            continue
        ns = ctx.score_item(item, persona_keywords)
        if persona_keywords and not ns.persona_matched:
            continue
        key = ctx.identity_key(item)
        out[key] = _Candidate(
            item=item,
            source_path=PATH_A,
            matched_keyword=item.summary or None,
            is_toutiao_hot=ns.is_toutiao_hot,
            is_hot_board=True,
            persona_matched=ns.persona_matched,
            preliminary_score=ns.score,
        )

    if sum(1 for c in out.values() if c.is_hot_board) >= filters.min_hot_board_before_search:
        return list(out.values())

    # Path B: per-keyword search results
    for extracted in keywords:
        phrase = extracted.keyword
        for item in search_results_by_keyword.get(phrase, []):
            key = ctx.identity_key(item)
            info = article_info_by_key.get(key)
            article_heat = int((info or {}).get("article_heat") or 0)
            if article_heat < filters.article_heat_min:
                continue
            enriched = ctx.enrich_with_article_info(item, info)
            ns = ctx.score_item(enriched, persona_keywords)
            cand = _Candidate(
                item=enriched,
                source_path=PATH_B,
                matched_keyword=phrase,
                is_toutiao_hot=bool(info and info.get("is_toutiao_hot")),
                is_hot_board=False,
                persona_matched=ns.persona_matched,
                preliminary_score=ns.score,
            )
            out[key] = _merge_candidates(out.get(key), cand)

    # Path C: is_toutiao_hot fallback (article_heat within fallback band)
    if filters.include_is_toutiao_hot_fallback:
        for phrase, items in search_results_by_keyword.items():
            for item in items:
                key = ctx.identity_key(item)
                info = article_info_by_key.get(key)
                if not info or not info.get("is_toutiao_hot"):
                    continue
                article_heat = int(info.get("article_heat") or 0)
                if not (
                    filters.is_toutiao_hot_min_article_heat
                    <= article_heat
                    <= filters.is_toutiao_hot_max_article_heat
                ):
                    continue
                enriched = ctx.enrich_with_article_info(item, info)
                ns = ctx.score_item(enriched, persona_keywords)
                cand = _Candidate(
                    item=enriched,
                    source_path=PATH_C,
                    matched_keyword=phrase,
                    is_toutiao_hot=True,
                    is_hot_board=False,
                    persona_matched=ns.persona_matched,
                    preliminary_score=ns.score,
                )
                out[key] = _merge_candidates(out.get(key), cand)

    return list(out.values())


def _merge_candidates(a: "Candidate | None", b: "Candidate") -> "Candidate":
    """Merge two candidates for the same article: keep higher score, union source_path."""
    from heated_topics_v3.toutiao_paths import Candidate as _Candidate
    if a is None:
        return b
    paths = sorted(set(a.source_path.split("+") + b.source_path.split("+")))
    primary = a if a.preliminary_score >= b.preliminary_score else b
    other = b if primary is a else a
    return _Candidate(
        item=primary.item,
        source_path="+".join(paths),
        matched_keyword=primary.matched_keyword or other.matched_keyword,
        is_toutiao_hot=primary.is_toutiao_hot or other.is_toutiao_hot,
        is_hot_board=primary.is_hot_board or other.is_hot_board,
        persona_matched=primary.persona_matched or other.persona_matched,
        preliminary_score=primary.preliminary_score,
    )
