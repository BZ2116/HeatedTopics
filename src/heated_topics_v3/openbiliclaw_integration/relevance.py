"""Embedding-based relevance scoring for V3 / last30days candidates.

Two heat sources:
- ``_heat_factor_from_rank(rank)``: 1/rank clamped to [0.05, 1.0]. Default;
  used when ``heat_source="rank"``.
- ``_heat_factor_from_view(view_count)``: log-scaled real engagement,
  used when ``heat_source="view"``. Falls back to rank when view_count
  is missing/zero.

``score_article`` returns the relevance score (``max_sim * heat_factor``)
or ``None`` if the article should be pre-filtered (``max_sim < threshold``).
``embed_keywords`` embeds each keyword once with per-call failure isolation.

Embedding lookup and cosine math live in openbiliclaw.llm.embedding
(``EmbeddingService.embed`` + ``cosine_similarity``). We just compose them.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from openbiliclaw.llm.embedding import cosine_similarity

if TYPE_CHECKING:
    from openbiliclaw.llm.embedding import EmbeddingService

logger = logging.getLogger(__name__)

_HEAT_FLOOR = 0.05
_HEAT_CEIL = 1.0
# Empirically calibrated for bge-m3 + Chinese short-text. Random off-topic
# articles cluster at sim 0.30-0.42 (Flutter UI ≈ 0.35, empty wechat stubs ≈
# 0.42). On-topic content starts at sim ≈ 0.50. 0.50 cleanly separates.
_SIM_THRESHOLD = 0.5
# log(view+1)/log(_VIEW_NORM+1) saturates at ~1.0 around view_count=100000.
# Below ~100 views the heat signal is noise; we still return _HEAT_FLOOR.
_VIEW_NORM = 100_000


def _heat_factor_from_rank(rank: int) -> float:
    """Rank → heat weight in [_HEAT_FLOOR, _HEAT_CEIL].

    rank 1 → 1.0, rank 10 → 0.10, rank 100 → 0.05 (floor). Non-positive
    ranks map to the floor (treated as "unknown / not on a hotlist").
    """
    if rank <= 0:
        return _HEAT_FLOOR
    raw = 1.0 / rank
    return max(_HEAT_FLOOR, min(_HEAT_CEIL, raw))


def _heat_factor_from_view(view_count: int) -> float:
    """view_count → heat weight in [_HEAT_FLOOR, _HEAT_CEIL].

    Log-scaled so a 100k-view article saturates at ~1.0 and a 100-view
    article lands around 0.6. view_count <= 0 → floor.

    Designed for platforms where the absolute view number is the right
    heat signal (e.g. 微博/B站/抖音 long-tail picks). Use ``heat_source``
    switch to opt in; off by default to preserve v2.1.2 behavior.
    """
    if view_count <= 0:
        return _HEAT_FLOOR
    raw = math.log(view_count + 1) / math.log(_VIEW_NORM + 1)
    return max(_HEAT_FLOOR, min(_HEAT_CEIL, raw))


def heat_factor(rank: int, view_count: int, source: str = "rank") -> float:
    """Resolve the right heat factor based on ``source``.

    ``source="view"`` uses ``_heat_factor_from_view`` when view_count > 0,
    falls back to ``_heat_factor_from_rank`` otherwise. ``source="rank"``
    (default) keeps the v2.1.2 1/rank behavior.
    """
    if source == "view" and view_count > 0:
        return _heat_factor_from_view(view_count)
    return _heat_factor_from_rank(rank)


def score_article(
    article_vec: list[float],
    keyword_vectors: list[list[float]],
    *,
    rank: int,
    threshold: float = _SIM_THRESHOLD,
    view_count: int = 0,
    heat_source: str = "rank",
) -> float | None:
    """Score one article against the keyword vectors.

    Returns ``max_sim * heat_factor`` if the best similarity meets
    ``threshold``; ``None`` to signal the article should be pre-filtered
    before reaching the engine.

    ``view_count`` + ``heat_source="view"`` switch the heat factor from
    rank-based to log-scaled real engagement. Zero-length article or
    keyword vectors are treated as no signal (not as +inf / NaN). A
    pure-zero best sim returns None.
    """
    if not keyword_vectors or not article_vec:
        return None
    sims = [
        cosine_similarity(article_vec, kv)
        for kv in keyword_vectors
        if kv  # skip zero-length keyword vectors
    ]
    if not sims:
        return None
    best = max(sims)
    if best < threshold:
        return None
    return best * heat_factor(rank, view_count, source=heat_source)


async def embed_keywords(
    keywords: list[str],
    embedding_service: EmbeddingService,
) -> list[list[float]]:
    """Embed each keyword once, in order. Empty results / exceptions dropped.

    Returns the list of successfully-computed vectors in input order. If
    every keyword fails, returns ``[]`` — callers should detect this and
    fall back to rank-based scoring rather than treating no vectors as
    "all match".
    """
    out: list[list[float]] = []
    for kw in keywords:
        try:
            vec = await embedding_service.embed(kw)
        except Exception as exc:
            logger.warning(
                "keyword embedding failed for %r: %s", kw, exc,
            )
            continue
        if vec:
            out.append(vec)
    return out
