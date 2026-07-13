"""Toutiao hot-board and single-keyword search provider."""
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, article_text, number_or_none

TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"
TOUTIAO_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ToutiaoProvider:
    def __init__(self, client: httpx.Client, rendered_fetcher: Callable[[str], str] | None = None):
        self.client = client
        self.rendered_fetcher = rendered_fetcher

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        raw = self.client.get(TOUTIAO_HOT_BOARD_URL).text
        return ProviderCapture(raw, ".json", self.parse_hot_list(raw, collected_at))

    def search(self, primary_keyword: str, collected_at: str) -> ProviderCapture:
        raw = self.client.get(TOUTIAO_SEARCH_URL, params={"keyword": primary_keyword}).text
        return ProviderCapture(raw, ".json", self.parse_search(raw, collected_at))

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        try:
            content = article_text(self.client.get(item.url).text)
        except Exception:
            content = ""
        method = "toutiao_article_page"
        if not content and self.rendered_fetcher:
            method = "toutiao_rendered_page"
            try:
                content = self.rendered_fetcher(item.url).strip()
            except Exception:
                content = ""
        if not content:
            content, method = (item.summary or item.title), ("source_summary" if item.summary else "title")
        return _detail(item, content, collected_at, method)

    @staticmethod
    def parse_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        rows = json.loads(raw).get("data", [])
        items = []
        for rank, row in enumerate(rows, 1):
            item_id, title, url = str(row.get("ClusterIdStr") or row.get("ClusterId") or ""), str(row.get("Title") or "").strip(), str(row.get("Url") or "").strip()
            if not (item_id and title and url): continue
            value = number_or_none(row.get("HotValue"))
            items.append(HotItem(f"toutiao_{item_id}", "toutiao", title, url, rank, HeatMetrics(value, "" if value is None else str(value), "hot_value", {} if value is None else {"hot_value": value}), str(row.get("QueryWord") or title), None, collected_at, row))
        return tuple(items)

    @staticmethod
    def parse_search(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        payload = json.loads(raw)
        if payload.get("dom"):
            return _parse_search_dom(str(payload["dom"]), collected_at)
        rows = payload.get("data", [])
        cutoff = _datetime(collected_at) - timedelta(hours=24)
        items = []
        for rank, row in enumerate(rows, 1):
            publication = row.get("publish_time") or row.get("publish_time_str")
            published = _optional_datetime(publication)
            if published and published < cutoff: continue
            title, url = str(row.get("title") or "").strip(), str(row.get("url") or "").strip()
            if not title or not url: continue
            reads, comments = number_or_none(row.get("read_count")), number_or_none(row.get("comment_count"))
            metrics = {k: v for k, v in (("reads", reads), ("comments", comments)) if v is not None}
            value = sum(metrics.values()) if metrics else max(len(rows) - rank + 1, 1)
            metric_name = "engagement" if metrics else "search_rank"
            item_id = str(row.get("id") or re.sub(r"\D", "", url) or rank)
            items.append(HotItem(f"toutiao_{item_id}", "toutiao", title, url, rank, HeatMetrics(value, str(value), metric_name, metrics or {"search_rank": value}), str(row.get("abstract") or title), str(publication) if published else None, collected_at, row))
        return tuple(items)


class _SearchDomParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.targets: list[str | None] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        group_id = str(attributes.get("data-group-id") or "")
        href = str(attributes.get("href") or "")
        href_match = re.search(r"/group/(\d+)(?:/|$)", href)
        if href_match:
            group_id = href_match.group(1)
        if group_id and (self.current is None or self.current.get("group_id") != group_id):
            self._finish_card()
            self.current = {
                "group_id": group_id,
                "url": f"https://www.toutiao.com/group/{group_id}/",
            }

        target = None
        if self.current:
            classes = str(attributes.get("class") or "").lower()
            if href_match or "title" in classes:
                target = "title"
            elif tag == "p" or "summary" in classes or "abstract" in classes:
                target = "abstract"
            elif "source" in classes:
                target = "source"
            elif tag == "time" or "time" in classes or "date" in classes:
                publication = attributes.get("datetime") or attributes.get("data-time")
                if publication:
                    self.current["publish_time"] = str(publication)
                else:
                    target = "publish_time"
        self.targets.append(target)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not self.current:
            return
        target = next((value for value in reversed(self.targets) if value), None)
        text = data.strip()
        if target and text:
            self.current[target] = " ".join(filter(None, (self.current.get(target), text)))

    def handle_endtag(self, tag: str) -> None:
        if self.targets:
            self.targets.pop()
        if tag == "article":
            self._finish_card()

    def close(self) -> None:
        super().close()
        self._finish_card()

    def _finish_card(self) -> None:
        if self.current and self.current.get("group_id") and self.current.get("title"):
            self.cards.append(self.current)
        self.current = None


def _parse_search_dom(dom: str, collected_at: str) -> tuple[HotItem, ...]:
    parser = _SearchDomParser()
    parser.feed(dom)
    parser.close()
    cutoff = _datetime(collected_at) - timedelta(hours=24)
    items = []
    for rank, row in enumerate(parser.cards, 1):
        publication = row.get("publish_time")
        published = _optional_datetime(publication)
        if published and published < cutoff:
            continue
        group_id = row["group_id"]
        items.append(HotItem(
            f"toutiao_{group_id}",
            "toutiao",
            row["title"],
            row["url"],
            rank,
            HeatMetrics(rank, str(rank), "search_rank", {"search_rank": rank}),
            row.get("abstract") or row["title"],
            str(publication) if published else None,
            collected_at,
            row,
        ))
    return tuple(items)


def _datetime(value) -> datetime:
    if isinstance(value, (int, float)) or str(value).isdigit(): return datetime.fromtimestamp(float(value), timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TOUTIAO_TIMEZONE)
    return parsed.astimezone(timezone.utc)

def _optional_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return _datetime(value)
    except (ValueError, TypeError, OverflowError):
        return None

def _detail(item, content, collected_at, method):
    status = "full_text" if method in {"toutiao_article_page", "toutiao_rendered_page"} else ("summary" if method == "source_summary" else "title_only")
    fetch_status = "success" if status == "full_text" else "partial"
    return ItemDetail(item.item_id, content, status, item.publication_time, collected_at, item.url, fetch_status)
