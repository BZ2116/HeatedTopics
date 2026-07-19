"""Pure parsers for Baidu board / search / article responses.

No I/O lives here — every function takes the response text and the matching
context, returns a domain object. Network access is owned by the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BaiduSearchArticle:
    article_id: str
    title: str
    url: str
    source_word: str
    platform: str = "baidu"


_BJH_HREF_RE = re.compile(
    r"baijiahao\.baidu\.com/s\?id=([A-Za-z0-9_\-]+)"
)


class _SearchLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_anchor = False
        self._article_id: str | None = None
        # When the anchor contains an <h3>, prefer its text for the title.
        # We accumulate h3 text parts here and ignore other text in that case.
        self._in_h3 = False
        self._h3_parts: list[str] = []
        self._has_h3 = False
        # Fallback path: when there is no <h3>, we collect all anchor text.
        self._all_parts: list[str] = []
        self._found: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v), "")
            m = _BJH_HREF_RE.search(href)
            if m:
                self._in_anchor = True
                self._article_id = m.group(1)
                self._h3_parts = []
                self._all_parts = []
                self._has_h3 = False
            return
        if self._in_anchor and tag == "h3":
            self._in_h3 = True
            self._has_h3 = True
            self._h3_parts.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            return
        if tag == "a" and self._in_anchor:
            if self._has_h3:
                title = " ".join("".join(self._h3_parts).split())
            else:
                title = " ".join("".join(self._all_parts).split())
            if self._article_id:
                # Always record the article_id so callers can dedup, even if the
                # title ended up empty (defensive: avoid letting a later real
                # title slip through after an empty-title duplicate).
                self._found.append((self._article_id, title))
            self._in_anchor = False
            self._article_id = None
            self._h3_parts = []
            self._all_parts = []
            self._has_h3 = False

    def handle_data(self, data: str) -> None:
        if not self._in_anchor:
            return
        if self._in_h3:
            # Append onto the current <h3> segment slot so nested tags don't
            # collapse multiple h3 sections into one string.
            self._h3_parts[-1] += data
        else:
            self._all_parts.append(data)

    def result(self) -> list[tuple[str, str]]:
        return self._found


def parse_baidu_search_response(
    response_text: str,
    source_word: str,
) -> list[BaiduSearchArticle]:
    parser = _SearchLinkParser()
    parser.feed(response_text)
    seen: set[str] = set()
    out: list[BaiduSearchArticle] = []
    for article_id, title in parser.result():
        if not article_id:
            continue
        if article_id in seen:
            continue
        # Mark as seen regardless of title content so an empty-title duplicate
        # cannot let a later real-title occurrence slip through.
        seen.add(article_id)
        if not title:
            continue
        url = f"https://baijiahao.baidu.com/s?id={article_id}"
        out.append(
            BaiduSearchArticle(
                article_id=article_id,
                title=title,
                url=url,
                source_word=source_word,
            )
        )
    return out