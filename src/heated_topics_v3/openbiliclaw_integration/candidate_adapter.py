"""Map V3 Article dicts to OpenBiliClaw DiscoveredContent."""

from __future__ import annotations

from typing import Any

from openbiliclaw.discovery.engine import DiscoveredContent

from heated_topics_v3.openbiliclaw_integration.exceptions import CandidateMappingError

_REQUIRED_FIELDS = ("article_id", "title", "url", "body_text")

# Floor mirrors the OpenBiliClaw engine: classification_failed rows use 0.01
# so callers can distinguish "never evaluated" from "evaluated but low score".
_RELEVANCE_FLOOR = 0.01


def _rank_to_relevance(rank: int) -> float:
    """Map a 1-based hot-list rank to a relevance score in [0.01, 1.0].

    Top items dominate: rank 1 -> 1.0, rank 2 -> 0.5, rank 5 -> 0.2, rank 10 -> 0.1,
    rank 100 -> 0.01 (floor). Missing/zero rank -> floor.

    The OpenBiliClaw engine's serve_external_candidates selector falls back
    to ``item.relevance_score`` when no curator is attached (the heatedTopics
    integration never passes one), and the ``Recommendation.confidence``
    field reads ``relevance_score`` verbatim. Without this mapping every
    candidate's relevance_score is 0.0, the MMR diversifier degenerates to
    diversity-only selection, and confidence always reports as 0.0.
    """
    if rank <= 0:
        return _RELEVANCE_FLOOR
    return max(_RELEVANCE_FLOOR, min(1.0, 1.0 / rank))


def to_discovered(
    articles: list[dict[str, Any]],
    *,
    platform: str,
) -> list[DiscoveredContent]:
    """Convert a list of V3 Article dicts to DiscoveredContent.

    Skips articles that lack required fields. Logs (does not raise) on
    individual skips; raises CandidateMappingError only if the input list
    is not a list.
    """
    if not isinstance(articles, list):
        raise CandidateMappingError(
            f"articles must be a list, got {type(articles).__name__}"
        )
    out: list[DiscoveredContent] = []
    for raw in articles:
        if not isinstance(raw, dict):
            continue
        missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            continue
        heat = raw.get("heat") or {}
        rank = int(heat.get("rank", 0))
        item = DiscoveredContent(
            title=str(raw["title"]),
            content_id=str(raw["article_id"]),
            content_url=str(raw["url"]),
            source_platform=str(raw.get("platform") or platform),
            body_text=str(raw["body_text"]),
            description=str(raw.get("summary", raw.get("description", ""))),
            author_name=str(raw.get("author", "")),
            published_at=str(raw.get("published_at", "")),
            tags=list(raw.get("tags", [])),
            view_count=int(heat.get("view", 0)),
            like_count=int(heat.get("like", 0)),
            comment_count=int(heat.get("comment", 0)),
            favorite_count=int(heat.get("favorite", 0)),
            share_count=int(heat.get("share", 0)),
            source_rank=rank,
            relevance_score=_rank_to_relevance(rank),
            content_type="note",
        )
        out.append(item)
    return out
