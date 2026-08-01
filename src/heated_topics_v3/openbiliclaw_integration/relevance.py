"""Embedding-based relevance scoring for V3 / last30days candidates.

Two components:
- ``_heat_factor(rank)``: 1/rank clamped to [0.05, 1.0]. Used as a tie-breaker
  when relevance signals are equal.
- ``score_article(article_vec, keyword_vectors, rank, threshold)``: returns
  the relevance score (``max_sim * heat_factor``) or ``None`` if the article
  should be pre-filtered (``max_sim < threshold``).
- ``embed_keywords(keywords, embedding_service)``: embeds each keyword once
  with per-call failure isolation.

Embedding lookup and cosine math live in openbiliclaw.llm.embedding
(``EmbeddingService.embed`` + ``cosine_similarity``). We just compose them.
"""

from __future__ import annotations

import logging
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


def _heat_factor(rank: int) -> float:
    """Rank → heat weight in [_HEAT_FLOOR, _HEAT_CEIL].

    rank 1 → 1.0, rank 10 → 0.10, rank 100 → 0.05 (floor). Non-positive
    ranks map to the floor (treated as "unknown / not on a hotlist").
    """
    if rank <= 0:
        return _HEAT_FLOOR
    raw = 1.0 / rank
    return max(_HEAT_FLOOR, min(_HEAT_CEIL, raw))


def score_article(
    article_vec: list[float],
    keyword_vectors: list[list[float]],
    *,
    rank: int,
    threshold: float = _SIM_THRESHOLD,
) -> float | None:
    """Score one article against the keyword vectors.

    Returns ``max_sim * heat_factor`` if the best similarity meets
    ``threshold``; ``None`` to signal the article should be pre-filtered
    before reaching the engine.

    Zero-length article or keyword vectors are treated as no signal
    (not as +inf / NaN). A pure-zero best sim returns None.
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
    return best * _heat_factor(rank)


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
