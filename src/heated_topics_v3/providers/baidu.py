"""Pure parsers for Baidu board / search / article responses.

No I/O lives here — every function takes the response text and the matching
context, returns a domain object. Network access is owned by the pipeline.
"""
from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from typing import Any

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail


def _safe_word_slug(word: str) -> str:
    """Stable identifier suffix for a hot word.

    Short words (<=24 chars) are used verbatim. Longer words are prefixed
    with a sha256 digest to keep ``item_id`` bounded.
    """
    if len(word) <= 24:
        return word
    digest = hashlib.sha256(word.encode("utf-8")).hexdigest()[:8]
    return f"{digest}_{word[:24]}"


def parse_baidu_board_response(
    response_text: str,
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
) -> list[HotItem]:
    payload = json.loads(response_text)
    if not payload.get("success"):
        return []
    cards = (payload.get("data") or {}).get("cards") or []
    if not cards:
        return []
    rows = ((cards[0].get("content") or [{}])[0].get("content")) or []
    items: list[HotItem] = []
    for row in rows:
        word = str(row.get("word", "")).strip()
        url = str(row.get("url", "")).strip()
        if not word or not url:
            continue
        heat_raw = row.get("hotTag")
        try:
            heat_value: int | None = int(heat_raw) if heat_raw is not None else None
        except (TypeError, ValueError):
            heat_value = None
        rank: int | None = None if row.get("isTop") else row.get("index")
        items.append(
            HotItem(
                item_id=f"baidu_word_{_safe_word_slug(word)}",
                platform="baidu",
                item_type="hotword",
                title=word,
                url=url,
                rank=int(rank) if isinstance(rank, (int, str)) and str(rank).isdigit() else None,
                heat=HeatMetrics(
                    value=heat_value,
                    label="" if heat_value is None else str(heat_value),
                    metric_name="hot_tag",
                    metrics={},
                ),
                summary="",
                category="baidu_hotword",
                matched_query_ids=matched_query_ids,
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload={"source_kind": "baidu_board", "raw": row},
            )
        )
    return items