"""Strict anonymous NetEase News hot-list, search, detail and comment provider."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urlparse

import httpx
from gne import GeneralNewsExtractor

from heated_topics_v3.content import extract_container_text, validate_full_text
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, ProviderContractError, number_or_none

NETEASE_HOT_URL = "https://gw.m.163.com/nc-main/api/v1/hqc/no-repeat-hot-list"
NETEASE_SEARCH_URL = "https://www.163.com/search"
NETEASE_ARTICLE_URL = "https://www.163.com/dy/article/{docid}.html"
NETEASE_SELECTORS = (".post_body", "#endText", ".post_text")
NETEASE_WEIGHTS = {
    "hot_value": 0.40,
    "click": 0.30,
    "comments": 0.15,
    "votes": 0.10,
    "thread_votes": 0.05,
}
NETEASE_ABSOLUTE_FLOORS = {"comments": 10.0}

NETEASE_TIMEZONE = timezone(timedelta(hours=8))
_CARD_SELECTOR = "keyword_new_list"
_DOCID_RE = re.compile(r"/(?:dy/article/|article/)(?P<docid>[A-Za-z0-9]+)\.html")
_EM_TAG_RE = re.compile(r"</?em[^>]*>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"(\d+)\s*条评论")


class _SearchCardParser(HTMLParser):
    """Capture each `.keyword_new_list` card and emit a tuple of fields.

    Fields per card: ``title`` (raw), ``href``, ``source``, ``time``,
    ``comments`` (visible count text). Card boundaries are tracked by
    entering a ``li`` whose descendants match ``keyword_new_list``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._in_card = False
        self._current: dict | None = None
        self._field: str | None = None
        self._depth = 0
        self._in_href = False
        self._href_attrs: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "li":
            self._in_card = True
            self._current = {
                "title": "",
                "href": "",
                "source": "",
                "time": "",
                "comments": "",
            }
            self._depth = 1
            return
        if not self._in_card:
            return
        values = {key.lower(): (value or "").strip() for key, value in attrs}
        classes = values.get("class", "").split()
        if values.get("class") and _CARD_SELECTOR in classes:
            self._depth += 1
        if tag == "a":
            href = values.get("href") or ""
            if not self._current["href"] and href:
                self._current["href"] = href
                self._in_href = True
                self._href_attrs = attrs
                self._field = "title"
        elif tag == "h3":
            self._field = "title"
        elif tag == "span":
            if not self._field:
                self._field = "source"
        elif tag == "p":
            cls = values.get("class", "")
            if "comment" in cls:
                self._field = "comments"
            elif "source" in cls:
                self._field = "source"
        elif tag == "div" and values.get("class"):
            self._depth += 1

    def handle_endtag(self, tag) -> None:
        if not self._in_card:
            return
        if tag == "li":
            if self._current is not None:
                self.cards.append(self._current)
            self._current = None
            self._in_card = False
            self._field = None
            self._depth = 0
            return
        if tag == "a":
            self._in_href = False
            self._field = None
        if tag == "div":
            if self._depth > 1:
                self._depth -= 1
        if tag in ("p", "h3", "span"):
            self._field = None

    def handle_data(self, data) -> None:
        if not self._in_card or self._current is None:
            return
        text = data.strip()
        if not text:
            return
        if self._field == "title":
            self._current["title"] += text
        elif self._field == "source":
            self._current["source"] = (
                self._current["source"] + " " + text
            ).strip()
        elif self._field == "comments":
            self._current["comments"] = (
                self._current["comments"] + " " + text
            ).strip()
        elif not self._current["source"] and self._field is None:
            # Time fallback: raw text on first non-titled data.
            self._current["time"] = (
                self._current["time"] + " " + text
            ).strip()


def _is_netease_article(url: str) -> bool:
    """Allow only canonical NetEase article URLs (not video, photo, live)."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host.endswith("163.com"):
        return False
    path = parsed.path or ""
    if not path.startswith("/dy/article/"):
        return False
    return True


def _extract_docid(url: str) -> str | None:
    if not _is_netease_article(url):
        return None
    match = _DOCID_RE.search(urlparse(url).path)
    return match.group("docid") if match else None


class NeteaseNewsProvider:
    def __init__(self, client: httpx.Client):
        self.client = client

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(NETEASE_HOT_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".json", self.parse_hot_list(raw, collected_at))

    def search(
        self,
        primary_keyword: str,
        collected_at: str,
        page: int = 1,
    ) -> ProviderCapture:
        response = self.client.get(
            NETEASE_SEARCH_URL, params={"keyword": primary_keyword}
        )
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".html", self.parse_search(raw, collected_at))

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        try:
            response = self.client.get(item.url)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPError:
            html = ""
        content, parser = self._extract_content(html)
        validation = validate_full_text(
            content, item.title, item.summary, parser=parser
        )
        if validation.status != "accepted":
            reasons = ",".join(validation.reasons) or "empty"
            return ItemDetail(
                item.item_id, "", "rejected", item.publication_time,
                collected_at, item.url, f"rejected:{reasons}",
            )
        return ItemDetail(
            item.item_id, content, "full_text", item.publication_time,
            collected_at, item.url, "success",
        )

    def enrich_metrics(
        self,
        items: HotItem | tuple[HotItem, ...],
        collected_at: str,
    ) -> tuple[HotItem, ...] | HotItem:
        if isinstance(items, HotItem):
            return items
        return items

    @staticmethod
    def parse_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        rows = _hot_items(raw)
        items: list[HotItem] = []
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            if row.get("type") != "doc":
                continue
            content_id = str(row.get("contentId") or "").strip()
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or NETEASE_ARTICLE_URL.format(
                docid=content_id
            )).strip()
            if not content_id or not title:
                continue
            metrics: dict[str, int] = {}
            for field, key in (
                ("hotValue", "hot_value"),
                ("click", "click"),
                ("commentCount", "comments"),
                ("votecount", "votes"),
                ("threadVote", "thread_votes"),
            ):
                value = number_or_none(row.get(field))
                if value is not None:
                    metrics[key] = value
            primary = metrics.get("hot_value")
            publication = _optional_datetime(row.get("ptime"))
            summary = str(row.get("source") or title)
            items.append(HotItem(
                f"netease_news_{content_id}",
                "netease_news",
                title,
                url,
                rank,
                HeatMetrics(
                    primary,
                    "" if primary is None else str(primary),
                    "hot_value",
                    metrics,
                ),
                summary,
                publication,
                collected_at,
                row,
            ))
        if not items:
            raise ProviderContractError("netease hot list contained no valid doc items")
        return tuple(items)

    @staticmethod
    def parse_search(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        cards = _search_cards(raw)
        items: list[HotItem] = []
        seen_docids: set[str] = set()
        for rank, card in enumerate(cards, 1):
            url = card.get("href", "").strip()
            docid = _extract_docid(url)
            if not docid:
                continue
            if docid in seen_docids:
                continue
            seen_docids.add(docid)
            title = _strip_em(card.get("title", "").strip())
            if not title:
                continue
            comments = _comment_count(card.get("comments", ""))
            metrics: dict[str, int] = {}
            if comments is not None:
                metrics["comments"] = comments
            publication = _optional_datetime(card.get("time", ""))
            source = card.get("source", "").strip()
            summary = source or title
            items.append(HotItem(
                f"netease_news_{docid}",
                "netease_news",
                title,
                NETEASE_ARTICLE_URL.format(docid=docid),
                rank,
                HeatMetrics(
                    metrics.get("comments"),
                    "" if not metrics else str(metrics["comments"]),
                    "public_engagement",
                    metrics,
                ),
                summary,
                publication,
                collected_at,
                {
                    "docid": docid,
                    "source": source,
                    "comment_count_text": card.get("comments", "").strip(),
                },
            ))
        return tuple(items)

    @staticmethod
    def _extract_content(html: str) -> tuple[str, str]:
        text = extract_container_text(html, NETEASE_SELECTORS)
        if text and validate_full_text(text, "", "", parser="netease_dom").status == "accepted":
            return text, "netease_dom"
        try:
            extracted = GeneralNewsExtractor().extract(html)
        except Exception:
            extracted = {}
        fallback = str(extracted.get("content") or "")
        return fallback, "gne"


def _hot_items(raw: str) -> list:
    if not raw or not raw.strip():
        raise ProviderContractError("netease hot response is empty")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderContractError("netease hot response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderContractError("netease hot response must be a JSON object")
    if payload.get("code") not in (0, "0", 200, "200"):
        raise ProviderContractError("netease hot response code is not success")
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ProviderContractError("netease hot response has no items")
    return items


def _search_cards(raw: str) -> list[dict]:
    if not raw or not raw.strip():
        return []
    parser = _SearchCardParser()
    parser.feed(raw)
    return parser.cards


def _strip_em(text: str) -> str:
    if not text:
        return text
    return " ".join(_EM_TAG_RE.sub("", text).split())


def _comment_count(text: str) -> int | None:
    if not text:
        return None
    match = _COMMENT_RE.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    digits = re.findall(r"\d+", text)
    if digits:
        try:
            return int(digits[0])
        except ValueError:
            return None
    return None


def _optional_datetime(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=NETEASE_TIMEZONE).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NETEASE_TIMEZONE)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")