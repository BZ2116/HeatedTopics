"""Map V3 Article dicts to OpenBiliClaw DiscoveredContent."""

from __future__ import annotations

import logging
from typing import Any

from openbiliclaw.discovery.engine import DiscoveredContent

from heated_topics_v3.openbiliclaw_integration.exceptions import CandidateMappingError

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("article_id", "title", "url", "body_text")

# Sources whose articles can't satisfy our "article body" contract: bilibili
# and douyin only carry descriptions (video platforms — no full body text),
# xiaohongshu needs login (public crawl returns nothing). This is a safety net
# — callers should normally exclude these from the driver config; the filter
# here protects against accidentally re-enabling them via `provider=` overrides.
BLOCKED_SOURCES: frozenset[str] = frozenset({"bilibili", "douyin", "xiaohongshu"})

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


def _article_text_for_embedding(raw: dict[str, Any]) -> str:
    """Compose the text used to embed a candidate article.

    Title dominates; description / summary / body prefix fill in the rest.
    Body is capped to avoid runaway embedding cost on long articles.
    """
    title = str(raw.get("title") or "").strip()
    summary = str(
        raw.get("summary") or raw.get("description") or ""
    ).strip()
    body = str(raw.get("body_text") or "").strip()
    body_prefix = body[:300]
    parts = [p for p in (title, summary, body_prefix) if p]
    return " | ".join(parts) if parts else title or "untitled"


async def to_discovered(
    articles: list[dict[str, Any]],
    *,
    platform: str,
    embedding_service: Any | None = None,
    keyword_vectors: list[list[float]] | None = None,
    sim_threshold: float = 0.5,
    min_view_count: int = 0,
    heat_source: str = "rank",
) -> list[DiscoveredContent]:
    """Convert a list of V3 Article dicts to DiscoveredContent.

    Embedding-based relevance scoring (v2.1.2): when ``keyword_vectors`` is
    provided, each article's title+summary is embedded and scored by max
    cosine similarity against the keyword vectors. Articles below
    ``sim_threshold`` are dropped. The final ``relevance_score`` is
    ``max_sim * heat_factor(rank, view_count, source=heat_source)``.

    Optional hard filters:
    - ``min_view_count``: drop candidates whose ``heat.view`` is below this
      threshold. Default 0 (no filter) so existing callers see no change.
    - ``heat_source``: ``"rank"`` (default, v2.1.2 behavior) uses
      ``1/rank``; ``"view"`` uses ``log(view_count+1)/log(100001)`` and
      falls back to rank when view_count is missing/zero.

    Falls back to ``1/rank`` (v2.1.1 behavior) when ``keyword_vectors`` is
    None / empty, when ``embedding_service`` is None, or when the per-article
    embed call fails / returns empty. Keeps backward compatibility for
    callers that don't pass embeddings.
    """
    from heated_topics_v3.openbiliclaw_integration.relevance import (
        score_article,
    )

    if not isinstance(articles, list):
        raise CandidateMappingError(
            f"articles must be a list, got {type(articles).__name__}"
        )
    use_embedding = bool(keyword_vectors) and embedding_service is not None
    out: list[DiscoveredContent] = []
    for raw in articles:
        if not isinstance(raw, dict):
            continue
        missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            continue
        raw_platform = raw.get("platform") or platform
        if raw_platform in BLOCKED_SOURCES or platform in BLOCKED_SOURCES:
            logger.debug(
                "dropping %r: blocked platform=%r",
                raw.get("article_id"), raw_platform,
            )
            continue
        heat = raw.get("heat") or {}
        rank = int(heat.get("rank", 0))
        view_count = int(heat.get("view", 0))

        # Hard filter on view count (opt-in; default off).
        if min_view_count > 0 and view_count < min_view_count:
            logger.debug(
                "dropping %r: view_count=%d < min_view_count=%d",
                raw.get("article_id"), view_count, min_view_count,
            )
            continue

        if use_embedding:
            text = _article_text_for_embedding(raw)
            try:
                article_vec = await embedding_service.embed(text)
            except Exception as exc:
                logger.warning(
                    "candidate embedding failed for %r: %s",
                    raw.get("article_id"), exc,
                )
                article_vec = []
            score: float | None = score_article(
                article_vec, keyword_vectors,
                rank=rank, view_count=view_count,
                threshold=sim_threshold, heat_source=heat_source,
            )
            if score is None:
                continue
        else:
            score = _rank_to_relevance(rank)

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
            view_count=view_count,
            like_count=int(heat.get("like", 0)),
            comment_count=int(heat.get("comment", 0)),
            favorite_count=int(heat.get("favorite", 0)),
            share_count=int(heat.get("share", 0)),
            source_rank=rank,
            relevance_score=score,
            content_type="note",
        )
        out.append(item)
    return out
