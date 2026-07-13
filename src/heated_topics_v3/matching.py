"""Deterministic matching and heat classification for the two-platform V1."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence
from unicodedata import normalize
from urllib.parse import unquote, urlsplit

from heated_topics_v3.contracts import (
    HotItem,
    ItemDetail,
    RecommendationItem,
    UserProfile,
)


TOUTIAO_UNVERIFIED_NOTICE = "来自头条关键词搜索，未发现官方热榜证据"


def _normalized_text(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())


def matches_primary_keyword(
    profile: UserProfile, item: HotItem, detail: ItemDetail | None = None
) -> bool:
    """Match only the saved primary keyword across source-provided text."""
    keyword = _normalized_text(profile.primary_keyword)
    if not keyword:
        return False
    fields = (item.title, item.summary, "" if detail is None else detail.content)
    return any(keyword in _normalized_text(field) for field in fields)


def _group_id(item: HotItem) -> str:
    for key in ("group_id", "groupId", "ClusterIdStr", "cluster_id"):
        value = item.raw_payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _canonical_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(parsed.path).rstrip("/")
    if not path:
        return None
    return f"{host}{path}"


def _same_group_id(board_item: HotItem, search_item: HotItem) -> bool:
    board_group_id = _group_id(board_item)
    search_group_id = _group_id(search_item)
    return bool(
        board_group_id and search_group_id and board_group_id == search_group_id
    )


def _same_canonical_url(board_item: HotItem, search_item: HotItem) -> bool:
    board_url = _canonical_url(board_item.url)
    search_url = _canonical_url(search_item.url)
    return bool(board_url and search_url and board_url == search_url)


def _same_normalized_title(board_item: HotItem, search_item: HotItem) -> bool:
    board_title = _normalized_text(board_item.title)
    search_title = _normalized_text(search_item.title)
    return bool(board_title and search_title and board_title == search_title)


def _find_overlap(
    board_items: Sequence[HotItem], search_item: HotItem
) -> tuple[int, str] | None:
    matchers = (
        ("group_id", _same_group_id),
        ("canonical_url", _same_canonical_url),
        ("normalized_title", _same_normalized_title),
    )
    for method, matcher in matchers:
        for index, board_item in enumerate(board_items):
            if matcher(board_item, search_item):
                return index, method
    return None


def _board_evidence(board_item: HotItem, overlap_method: str | None = None) -> dict:
    evidence = {
        "source_kind": "official_hot_board",
        "board_item_id": board_item.item_id,
        "rank": board_item.rank,
        "metric_name": board_item.heat.metric_name,
        "heat_value": board_item.heat.value,
        "source_url": board_item.url,
    }
    if overlap_method is not None:
        evidence["overlap_method"] = overlap_method
    return evidence


def _with_evidence(item: HotItem, evidence: Mapping[str, object]) -> HotItem:
    raw_payload = dict(item.raw_payload)
    raw_payload["v1_evidence"] = dict(evidence)
    return replace(item, raw_payload=raw_payload)


def merge_toutiao_results(
    board: Sequence[HotItem], search: Sequence[HotItem]
) -> tuple[HotItem, ...]:
    """Join search records to the board, preserving official then search order."""
    board_items = tuple(board)
    overlapping: dict[int, list[HotItem]] = {}
    unmatched: list[HotItem] = []

    for search_item in search:
        match = _find_overlap(board_items, search_item)
        if match is None:
            evidence = {
                "source_kind": "keyword_search",
                "rank": search_item.rank,
                "metric_name": search_item.heat.metric_name,
                "notice": TOUTIAO_UNVERIFIED_NOTICE,
                "source_url": search_item.url,
            }
            unmatched.append(_with_evidence(search_item, evidence))
            continue

        board_index, overlap_method = match
        board_item = board_items[board_index]
        merged = replace(
            search_item,
            rank=board_item.rank,
            heat=board_item.heat,
        )
        overlapping.setdefault(board_index, []).append(
            _with_evidence(merged, _board_evidence(board_item, overlap_method))
        )

    official: list[HotItem] = []
    for index, board_item in enumerate(board_items):
        official.extend(
            overlapping.get(
                index,
                [_with_evidence(board_item, _board_evidence(board_item))],
            )
        )
    return tuple((*official, *unmatched))


def _recommendation(item: HotItem, detail: ItemDetail | None, heat_level: int) -> RecommendationItem:
    if detail is not None and detail.content.strip():
        content = detail.content
        content_status = detail.content_status
    elif item.summary:
        content = item.summary
        content_status = "summary"
    else:
        content = item.title
        content_status = "title_only"

    evidence = dict(item.raw_payload.get("v1_evidence", {}))
    if item.platform == "juejin":
        evidence = {
            "source_kind": "official_hot_rank",
            "rank": item.rank,
            "metric_name": item.heat.metric_name,
            "heat_value": item.heat.value,
            "metrics": dict(item.heat.metrics),
            "source_url": item.url,
        }
    return RecommendationItem(
        hot_item_id=item.item_id,
        platform=item.platform,
        title=item.title,
        heat_level=heat_level,
        fact_status="unverified",
        publication_time=item.publication_time,
        collected_at=item.collected_at,
        detail=content,
        content_status=content_status,
        is_personalized=True,
        evidence=evidence,
        source_url=item.url,
    )


def build_v1_recommendations(
    profile: UserProfile,
    toutiao_board: Sequence[HotItem],
    toutiao_search: Sequence[HotItem],
    juejin_board: Sequence[HotItem],
    details: Mapping[str, ItemDetail],
) -> tuple[RecommendationItem, ...]:
    """Build matched Toutiao then Juejin recommendations without cross-platform dedup."""
    recommendations: list[RecommendationItem] = []
    for item in merge_toutiao_results(toutiao_board, toutiao_search):
        item_detail = details.get(item.item_id)
        evidence = item.raw_payload.get("v1_evidence", {})
        board_item_id = evidence.get("board_item_id")
        board_detail = (
            details.get(str(board_item_id)) if board_item_id is not None else None
        )
        matched_detail = None
        if matches_primary_keyword(profile, item, item_detail):
            matched_detail = item_detail
        elif board_detail is not item_detail and matches_primary_keyword(
            profile, item, board_detail
        ):
            matched_detail = board_detail
        else:
            continue

        if matched_detail is None and board_detail is not None:
            matched_detail = board_detail
        heat_level = 3 if evidence.get("source_kind") == "keyword_search" else 1
        recommendations.append(_recommendation(item, matched_detail, heat_level))

    for item in juejin_board:
        item_detail = details.get(item.item_id)
        if matches_primary_keyword(profile, item, item_detail):
            recommendations.append(_recommendation(item, item_detail, 1))
    return tuple(recommendations)
