"""Three-path candidate builder for Toutiao.

Path A: Hot board priority (HotValue ≥ filters.hot_board_min, persona match)
Path B: Search by extracted keywords (article_heat > filters.article_heat_min)
Path C: is_toutiao_hot fallback (article_heat < 500 but is_toutiao_hot=true)

Cross-path dedup is by article_id (resolved through /search/jump wrappers),
so different articles from the same keyword search remain distinct candidates
even though their URLs canonicalize to the same path. Same article appearing
in multiple paths merges source_path (e.g. "A+B") and keeps the higher
preliminary score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from heated_topics_v3.contracts import ExtractedKeyword, HotItem
from heated_topics_v3.providers.toutiao import (
    extract_toutiao_article_id,
    resolve_toutiao_content_url,
)
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
    article_heat_min: int = 500
    is_toutiao_hot_min_article_heat: int = 0
    is_toutiao_hot_max_article_heat: int = 500
    include_is_toutiao_hot_fallback: bool = True
    search_pages: int = 1
    per_page: int = 10
    min_hot_board_before_search: int = 5


def build_hot_board_candidates(
    *,
    hot_board: list[HotItem],
    persona_keywords: tuple[str, ...] = (),
    filters: PathFilters = PathFilters(),
) -> list[Candidate]:
    """Path A only — hot board candidates passing hot_board_min + persona filter.

    Deduped by article_id (so callers can compare counts against Path B later).
    """
    candidates_by_key: dict[str, Candidate] = {}
    for item in hot_board:
        scored = hybrid_score_v2(item, persona_keywords)
        if not scored.is_hot_board:
            continue
        if (item.heat.value or 0) < filters.hot_board_min:
            continue
        if persona_keywords and not scored.persona_matched:
            continue
        key = _dedup_key_for(item)
        candidates_by_key[key] = Candidate(
            item=item,
            source_path=PATH_A,
            matched_keyword=item.summary or None,
            is_toutiao_hot=scored.is_toutiao_hot,
            is_hot_board=True,
            persona_matched=scored.persona_matched,
            preliminary_score=scored.score,
        )
    return list(candidates_by_key.values())


def build_candidates(
    *,
    hot_board: list[HotItem],
    keywords: tuple[ExtractedKeyword, ...] = (),
    persona_keywords: tuple[str, ...] = (),
    search_results_by_keyword: dict[str, list[HotItem]] | None = None,
    article_info_by_url: dict[str, dict[str, Any]] | None = None,
    filters: PathFilters = PathFilters(),
) -> list[Candidate]:
    """Construct candidates from paths A/B/C, deduped by article_id, ready for scoring.

    Search gate: if Path A already yields at least `filters.min_hot_board_before_search`
    candidates, Path B and Path C are skipped entirely.
    """
    search_results_by_keyword = search_results_by_keyword or {}
    article_info_by_url = article_info_by_url or {}
    candidates_by_key: dict[str, Candidate] = {
        _dedup_key_for(c.item): c
        for c in build_hot_board_candidates(
            hot_board=hot_board,
            persona_keywords=persona_keywords,
            filters=filters,
        )
    }

    if sum(1 for c in candidates_by_key.values() if c.is_hot_board) >= filters.min_hot_board_before_search:
        return list(candidates_by_key.values())

    # Path B — search by extracted keywords (article_heat >= filters.article_heat_min)
    for extracted in keywords:
        phrase = extracted.keyword
        search_items = search_results_by_keyword.get(phrase, [])
        for item in search_items:
            lookup_url = _canonical_url(item.url)
            info = article_info_by_url.get(lookup_url)
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
            key = _dedup_key_for(item)
            existing = candidates_by_key.get(key)
            if existing is None:
                candidates_by_key[key] = candidate
            else:
                candidates_by_key[key] = _merge_candidates(existing, candidate)

    # Path C — is_toutiao_hot fallback (article_heat < 500)
    if filters.include_is_toutiao_hot_fallback:
        for phrase, search_items in search_results_by_keyword.items():
            for item in search_items:
                lookup_url = _canonical_url(item.url)
                info = article_info_by_url.get(lookup_url)
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
                key = _dedup_key_for(item)
                existing = candidates_by_key.get(key)
                if existing is None:
                    candidates_by_key[key] = candidate
                else:
                    candidates_by_key[key] = _merge_candidates(existing, candidate)

    return list(candidates_by_key.values())


def _merge_candidates(a: Candidate, b: Candidate) -> Candidate:
    """Merge two candidates for the same article: keep higher score, union source_path."""
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


def _dedup_key_for(item: HotItem) -> str:
    """Compute a dedup key that survives search/jump URL wrapping.

    Current search results return URLs like
    `/search/jump?aid=1455&jtoken=...&url=...&h5_url=...%252Fgroup%252F{id}%252F`
    where the real article_id is buried in the nested h5_url. Using
    `_canonical_url` on those collapses every search item to `/search/jump`,
    destroying the candidate set. We resolve the URL and pull the article_id
    out so distinct articles remain distinct candidates.
    """
    resolved = resolve_toutiao_content_url(item.url)
    article_id = extract_toutiao_article_id(resolved)
    if article_id:
        return f"aid:{article_id}"
    return f"url:{_canonical_url(item.url)}"


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


@dataclass(frozen=True)
class HeatSelection:
    high_threshold: int = 10_000
    min_high_count: int = 5
    fallback_top_n: int = 15


def select_search_candidates_by_heat(
    candidates: list[Candidate],
    *,
    selection: HeatSelection = HeatSelection(),
) -> list[Candidate]:
    """Adaptive top-N selection for search-derived candidates.

    Path A (hot board) candidates are always kept.
    For Path B/C (search) candidates:
      - If at least `min_high_count` have article_heat >= `high_threshold`,
        keep only those (no count cap here; the pipeline's top_n caps above).
      - Otherwise, keep the top `fallback_top_n` by article_heat desc.
    """
    hot_board = [c for c in candidates if c.is_hot_board]
    search = [c for c in candidates if not c.is_hot_board]

    def heat_of(c: Candidate) -> int:
        return int((c.item.raw_payload or {}).get("article_heat", 0) or 0)

    search_sorted = sorted(search, key=heat_of, reverse=True)
    high_heat = [c for c in search_sorted if heat_of(c) >= selection.high_threshold]
    if len(high_heat) >= selection.min_high_count:
        return hot_board + high_heat
    return hot_board + search_sorted[: selection.fallback_top_n]
