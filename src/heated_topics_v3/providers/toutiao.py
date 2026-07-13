"""Toutiao hot-board and single-keyword search provider."""
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Callable

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture

TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"


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
        content = _article_text(self.client.get(item.url).text)
        method = "toutiao_article_page"
        if not content and self.rendered_fetcher:
            content, method = self.rendered_fetcher(item.url).strip(), "toutiao_rendered_page"
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
            value = _number(row.get("HotValue"))
            items.append(HotItem(f"toutiao_{item_id}", "toutiao", title, url, rank, HeatMetrics(value, "" if value is None else str(value), "hot_value", {} if value is None else {"hot_value": value}), str(row.get("QueryWord") or title), None, collected_at, row))
        return tuple(items)

    @staticmethod
    def parse_search(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        payload = json.loads(raw)
        rows = payload.get("data", [])
        cutoff = _datetime(collected_at) - timedelta(hours=24)
        items = []
        for rank, row in enumerate(rows, 1):
            publication = row.get("publish_time") or row.get("publish_time_str")
            published = _datetime(publication) if publication else None
            if published and published < cutoff: continue
            title, url = str(row.get("title") or "").strip(), str(row.get("url") or "").strip()
            if not title or not url: continue
            reads, comments = _number(row.get("read_count")), _number(row.get("comment_count"))
            metrics = {k: v for k, v in (("reads", reads), ("comments", comments)) if v is not None}
            value = sum(metrics.values()) if metrics else max(len(rows) - rank + 1, 1)
            metric_name = "engagement" if metrics else "search_rank"
            item_id = str(row.get("id") or re.sub(r"\D", "", url) or rank)
            items.append(HotItem(f"toutiao_{item_id}", "toutiao", title, url, rank, HeatMetrics(value, str(value), metric_name, metrics or {"search_rank": value}), str(row.get("abstract") or title), str(publication) if publication else None, collected_at, row))
        return tuple(items)


def _number(value):
    try: return int(float(value))
    except (TypeError, ValueError): return None

def _datetime(value) -> datetime:
    if isinstance(value, (int, float)) or str(value).isdigit(): return datetime.fromtimestamp(float(value), timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

class _ArticleParser(HTMLParser):
    def __init__(self): super().__init__(); self.depth = 0; self.parts = []; self.ignored = 0
    def handle_starttag(self, tag, attrs):
        if self.depth and tag in {"script", "style"}: self.ignored += 1
        elif tag == "article": self.depth = 1
        elif self.depth: self.depth += 1
    def handle_endtag(self, tag):
        if self.ignored:
            if tag in {"script", "style"}: self.ignored -= 1
        elif self.depth: self.depth -= 1
    def handle_data(self, data):
        if self.depth and not self.ignored and data.strip(): self.parts.append(data.strip())

def _article_text(html: str) -> str:
    parser = _ArticleParser(); parser.feed(html); return "\n".join(parser.parts)

def _detail(item, content, collected_at, method):
    status = "full_text" if method in {"toutiao_article_page", "toutiao_rendered_page"} else ("summary" if method == "source_summary" else "title_only")
    fetch_status = "success" if status == "full_text" else "partial"
    return ItemDetail(item.item_id, content, status, item.publication_time, collected_at, item.url, fetch_status)
