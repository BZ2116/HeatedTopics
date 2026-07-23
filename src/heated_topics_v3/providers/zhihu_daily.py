"""Strict anonymous Zhihu Daily latest-board and detail provider."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from typing import Any, Iterable, Mapping, Sequence
from unicodedata import normalize

import httpx

from heated_topics_v3.content import validate_full_text
from heated_topics_v3.contracts import HeatEvidence, HeatMetrics, HotItem

from .common import (
    ProviderCapture,
    ProviderContractError,
    number_or_none,
)


ZHIHU_DAILY_LATEST_URL = "https://daily.zhihu.com/api/4/news/latest"
ZHIHU_DAILY_DETAIL_URL = "https://daily.zhihu.com/api/4/news/{story_id}"

ZHIHU_DAILY_WEIGHTS: dict[str, float] = {}
ZHIHU_DAILY_ABSOLUTE_FLOORS: dict[str, float] = {}

_BLOCK_TAGS = {
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "pre",
    "section",
}
_IGNORED_TAGS = {"script", "style", "nav", "footer"}
_VOID_TAGS = {"br", "hr", "img"}


class ZhihuDailyProvider:
    platform = "zhihu_daily"
    weights = ZHIHU_DAILY_WEIGHTS
    absolute_floors = ZHIHU_DAILY_ABSOLUTE_FLOORS

    def __init__(self, client: httpx.Client):
        self.client = client

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(ZHIHU_DAILY_LATEST_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".json", self.parse_latest(raw, collected_at))

    def fetch_detail(self, item: HotItem, collected_at: str) -> "ItemDetail":
        try:
            response = self.client.get(ZHIHU_DAILY_DETAIL_URL.format(story_id=_story_id(item)))
        except httpx.HTTPError:
            return self._rejected(item, collected_at, "rejected:fetch_error")
        try:
            payload = response.json()
        except ValueError:
            return self._rejected(item, collected_at, "rejected:malformed_detail")
        if not isinstance(payload, dict):
            return self._rejected(item, collected_at, "rejected:malformed_detail")
        body = _extract_body_paragraphs(str(payload.get("body") or ""))
        source_url = str(payload.get("share_url") or item.url).strip() or item.url
        validation = validate_full_text(body, item.title, item.summary, parser="zhihu_dom")
        if validation.status != "accepted":
            reasons = ",".join(validation.reasons) or "empty"
            return self._rejected(item, collected_at, f"rejected:{reasons}", source_url=source_url)
        return ItemDetail(
            item.item_id, body, "full_text", item.publication_time,
            collected_at, source_url, "success",
        )

    def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        return ProviderCapture("", ".json", ())

    def build_board_evidence(
        self, item: HotItem, floors: Mapping[str, float]
    ) -> HeatEvidence | None:
        if item.rank is None or item.rank <= 0:
            return None
        return HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=item.rank,
            native_hot_value=None,
            metrics={},
            threshold_metrics=dict(floors),
            qualified_by=("official_hot_board",),
        )

    def build_search_evidence(
        self, item: HotItem, floors: Mapping[str, float]
    ) -> HeatEvidence | None:
        return None

    def enrich_metrics(
        self,
        items: Sequence[HotItem],
        collected_at: str,
    ) -> tuple[HotItem, ...]:
        return tuple(items)

    def _rejected(
        self,
        item: HotItem,
        collected_at: str,
        fetch_status: str,
        *,
        source_url: str | None = None,
    ) -> "ItemDetail":
        return ItemDetail(
            item.item_id, "", "rejected", item.publication_time,
            collected_at, source_url or item.url, fetch_status,
        )

    @staticmethod
    def parse_latest(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ProviderContractError("zhihu daily payload is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ProviderContractError("zhihu daily payload must be a JSON object")
        recommendation_date = str(payload.get("date") or "").strip()
        stories = payload.get("stories")
        if not isinstance(stories, list) or not stories:
            raise ProviderContractError("zhihu daily stories missing or empty")
        items: list[HotItem] = []
        for row in stories:
            if not isinstance(row, dict):
                continue
            if int(row.get("type", 0) or 0) != 0:
                continue
            story_id = number_or_none(row.get("id"))
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            if story_id is None or not title or not url:
                continue
            items.append(
                HotItem(
                    item_id=f"zhihu_daily_{story_id}",
                    platform="zhihu_daily",
                    title=title,
                    url=url,
                    rank=len(items) + 1,
                    heat=HeatMetrics(None, "", "rank", {}),
                    summary=str(row.get("hint") or "").strip(),
                    publication_time=None,
                    collected_at=collected_at,
                    raw_payload={
                        "recommendation_date": recommendation_date,
                        "story_id": story_id,
                        "hint": row.get("hint"),
                        "images": row.get("images"),
                    },
                )
            )
        if not items:
            raise ProviderContractError("zhihu daily stories contained no type=0 entries")
        return tuple(items)


class _BodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.ignored = 0
        self.parts: list[str] = []
        self.current: list[str] = []

    def _flush(self) -> None:
        paragraph = " ".join(self.current).strip()
        if paragraph:
            self.parts.append(paragraph)
        self.current.clear()

    def handle_starttag(self, tag, attrs) -> None:
        if self.ignored:
            if tag in _IGNORED_TAGS:
                self.ignored += 1
            elif tag not in _VOID_TAGS:
                self.depth += 1
            return
        if tag in _IGNORED_TAGS:
            self.ignored = 1
            return
        if tag in _BLOCK_TAGS or tag == "br":
            self._flush()
        if tag not in _VOID_TAGS:
            self.depth += 1

    def handle_endtag(self, tag) -> None:
        if not self.depth and not self.ignored:
            return
        if self.ignored:
            self.ignored -= 1
            if tag not in _VOID_TAGS and self.depth:
                self.depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _VOID_TAGS:
            return
        self.depth -= 1

    def handle_startendtag(self, tag, attrs) -> None:
        if tag == "br" and not self.ignored and self.depth:
            self._flush()

    def handle_data(self, data) -> None:
        if self.ignored or not self.depth:
            return
        text = " ".join(data.split())
        if text:
            self.current.append(text)


def _extract_body_paragraphs(html: str) -> str:
    parser = _BodyParser()
    parser.feed(html)
    return "\n".join(parser.parts)


def _story_id(item: HotItem) -> str:
    identifier = item.item_id.split("_")[-1] if item.item_id else ""
    if identifier.isdigit():
        return identifier
    return str(item.raw_payload.get("story_id") or "0")


from heated_topics_v3.contracts import ItemDetail  # noqa: E402  pylint: disable=wrong-import-position
