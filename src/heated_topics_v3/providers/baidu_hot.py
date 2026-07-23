"""Strict anonymous Baidu Hot Search official board provider."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Sequence
from unicodedata import normalize

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem

from .common import ProviderCapture, ProviderContractError, number_or_none


BAIDU_HOT_URL = "https://top.baidu.com/board?tab=realtime"
BAIDU_WEIGHTS: dict[str, float] = {"hot_score": 1.0}
BAIDU_ABSOLUTE_FLOORS: dict[str, float] = {"hot_score": 1.0}

_S_DATA = re.compile(r"<!--s-data:(.*?)-->", re.DOTALL)


class BaiduHotProvider:
    platform = "baidu_hot"
    weights = BAIDU_WEIGHTS
    absolute_floors = BAIDU_ABSOLUTE_FLOORS

    def __init__(self, client: httpx.Client):
        self.client = client

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(BAIDU_HOT_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".html", self.parse_hot_list(raw, collected_at))

    @staticmethod
    def parse_hot_list(raw_html: str, collected_at: str) -> tuple[HotItem, ...]:
        marker = _S_DATA.search(raw_html)
        if not marker:
            raise ProviderContractError("missing baidu s-data marker")
        try:
            envelope = json.loads(marker.group(1).strip())
        except (TypeError, ValueError) as error:
            raise ProviderContractError("malformed baidu s-data payload") from error
        if not isinstance(envelope, dict):
            raise ProviderContractError("baidu s-data must be a JSON object")

        rows = _resolve_content(envelope)
        if not rows:
            raise ProviderContractError("baidu board has no content rows")

        items: list[HotItem] = []
        for row in rows:
            parsed = _row_to_event(row, collected_at, rank=len(items) + 1)
            if parsed is None:
                continue
            items.append(parsed)
        if not items:
            raise ProviderContractError("baidu board contains no valid hot events")
        return tuple(items)

    def fetch_detail(self, item: HotItem, collected_at: str) -> "ItemDetail":  # pragma: no cover - placeholder for Task 3
        raise NotImplementedError("baidu fetch_detail belongs to Task 3")

    def search(  # pragma: no cover - placeholder for Task 3
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        raise NotImplementedError("baidu search belongs to Task 3")

    def enrich_metrics(
        self,
        items: Sequence[HotItem],
        collected_at: str,
    ) -> tuple[HotItem, ...]:
        return tuple(items)


def _resolve_content(envelope: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield the hot-event rows from either observed Baidu envelope.

    Accepted shapes:

    * ``{"data": {"cards": [ {"content": [...]} ]}}`` (newer envelope)
    * ``{"cards": [ {"content": [...]} ]}`` (older envelope)

    In both cases, an inner ``content`` list nested inside the first row is
    unwrapped one level so a wrapper row never reaches the row parser.
    """

    for candidate in (
        envelope.get("data", {}).get("cards") if isinstance(envelope.get("data"), dict) else None,
        envelope.get("cards"),
    ):
        if not candidate:
            continue
        for card in candidate:
            if not isinstance(card, dict):
                continue
            content = card.get("content")
            if not isinstance(content, list):
                continue
            if content and isinstance(content[0], dict) and isinstance(content[0].get("content"), list):
                content = content[0]["content"]
            for row in content:
                if isinstance(row, dict):
                    yield row
        return
    return


def _row_to_event(row: dict[str, Any], collected_at: str, *, rank: int) -> HotItem | None:
    title = (row.get("word") or row.get("title") or "").strip()
    query = (row.get("query") or title).strip()
    if not title or not query:
        return None
    hot_score = number_or_none(row.get("hotScore") or row.get("hotTag"))
    if hot_score is None:
        return None
    description = (row.get("desc") or "").strip()
    url = (row.get("rawUrl") or row.get("url") or "").strip()
    item_id = _stable_event_id(query)
    raw_payload = {
        "index": row.get("index"),
        "query": query,
        "rawUrl": row.get("rawUrl"),
        "url": row.get("url"),
        "img": row.get("img"),
        "hotTag": row.get("hotTag"),
        "hotScore": row.get("hotScore"),
    }
    return HotItem(
        item_id=item_id,
        platform="baidu_hot",
        title=title,
        url=url or f"https://top.baidu.com/board?tab=realtime#{item_id}",
        rank=rank,
        heat=HeatMetrics(
            value=int(hot_score),
            label=str(int(hot_score)),
            metric_name="hot_score",
            metrics={"hot_score": float(hot_score)},
        ),
        summary=description,
        publication_time=None,
        collected_at=collected_at,
        raw_payload={k: v for k, v in raw_payload.items() if v not in (None, "")},
    )


def _stable_event_id(query: str) -> str:
    normalized = " ".join(normalize("NFKC", query).casefold().split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"baidu_hot_{digest}"


# Late import to avoid an import cycle with contracts (used in Task 3 placeholder).
from heated_topics_v3.contracts import ItemDetail  # noqa: E402  pylint: disable=wrong-import-position


_replace = replace  # re-export for use by Task 3 logic if needed
