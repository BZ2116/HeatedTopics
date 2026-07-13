"""Toutiao hot-board and single-keyword search provider."""
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, ProviderContractError, article_text, number_or_none

TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"
TOUTIAO_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ToutiaoProvider:
    def __init__(self, client: httpx.Client, rendered_fetcher: Callable[[str], str] | None = None):
        self.client = client
        self.rendered_fetcher = rendered_fetcher

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(TOUTIAO_HOT_BOARD_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".json", self.parse_hot_list(raw, collected_at))

    def search(self, primary_keyword: str, collected_at: str) -> ProviderCapture:
        response = self.client.get(TOUTIAO_SEARCH_URL, params={
            "keyword": primary_keyword,
            "pd": "information",
            "source": "search_subtab_switch",
            "from": "information",
            "format": "json",
            "count": 10,
            "offset": 0,
        })
        response.raise_for_status()
        raw = response.text
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
        payload = _object_payload(raw)
        rows = payload.get("data")
        if payload.get("status") != "success" or not isinstance(rows, list) or not rows:
            raise ProviderContractError("invalid toutiao hot-board response")
        items = []
        for rank, row in enumerate(rows, 1):
            item_id, title, url = str(row.get("ClusterIdStr") or row.get("ClusterId") or ""), str(row.get("Title") or "").strip(), str(row.get("Url") or "").strip()
            if not (item_id and title and url): continue
            value = number_or_none(row.get("HotValue"))
            items.append(HotItem(f"toutiao_{item_id}", "toutiao", title, url, rank, HeatMetrics(value, "" if value is None else str(value), "hot_value", {} if value is None else {"hot_value": value}), str(row.get("QueryWord") or title), None, collected_at, row))
        if not items:
            raise ProviderContractError("toutiao hot board contained no valid items")
        return tuple(items)

    @staticmethod
    def parse_search(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        payload = _object_payload(raw)
        if "status" in payload and payload.get("status") != "success":
            raise ProviderContractError("toutiao search reported failure")
        if "dom" in payload:
            count = payload.get("count")
            dom = payload.get("dom")
            if (
                type(count) is not int
                or count < 0
                or not isinstance(dom, str)
            ):
                raise ProviderContractError("invalid toutiao search response")
            if count == 0:
                if dom.strip():
                    raise ProviderContractError(
                        "zero-count toutiao search returned nonempty DOM"
                    )
                return ()
            if not dom.strip():
                raise ProviderContractError("toutiao search omitted result DOM")
            return _parse_search_dom(dom, collected_at)
        if "data" not in payload or not isinstance(payload["data"], list):
            raise ProviderContractError("invalid toutiao search response")
        rows = payload["data"]
        if not rows:
            count = payload.get("count")
            if type(count) is not int or count != 0:
                raise ProviderContractError("ambiguous empty toutiao search response")
            return ()
        cutoff = _datetime(collected_at) - timedelta(hours=24)
        items = []
        valid_rows = 0
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            publication = row.get("publish_time") or row.get("publish_time_str")
            published = _optional_datetime(publication)
            title, url = str(row.get("title") or "").strip(), str(row.get("url") or "").strip()
            if not title or not url: continue
            valid_rows += 1
            if published and published < cutoff: continue
            reads, comments = number_or_none(row.get("read_count")), number_or_none(row.get("comment_count"))
            metrics = {k: v for k, v in (("reads", reads), ("comments", comments)) if v is not None}
            value = sum(metrics.values()) if metrics else max(len(rows) - rank + 1, 1)
            metric_name = "engagement" if metrics else "search_rank"
            item_id = str(row.get("id") or re.sub(r"\D", "", url) or rank)
            items.append(HotItem(f"toutiao_{item_id}", "toutiao", title, url, rank, HeatMetrics(value, str(value), metric_name, metrics or {"search_rank": value}), str(row.get("abstract") or title), str(publication) if published else None, collected_at, row))
        if rows and valid_rows == 0:
            raise ProviderContractError("toutiao legacy search contained no valid rows")
        return tuple(items)


class _SearchDomParser(HTMLParser):
    _VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.frames: list[tuple[str, str | None, bool]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set(str(attributes.get("class") or "").lower().split())
        card_root = "result-content" in classes or (tag == "article" and bool(attributes.get("data-group-id")))
        cr_params = _json_attribute(attributes.get("cr-params"))
        log_extra = _json_attribute(attributes.get("data-log-extra"))
        group_id = str(attributes.get("data-group-id") or "")
        href = str(attributes.get("href") or "")
        decoded_href = unquote(unquote(href))
        href_match = re.search(r"/group/(\d+)(?:/|$|\?)", decoded_href)
        if href_match:
            group_id = href_match.group(1)
        group_id = str(cr_params.get("gid") or cr_params.get("group_id") or log_extra.get("group_id") or group_id)

        if card_root:
            self._finish_card()
            self.current = {}
        elif group_id and (self.current is None or self.current.get("group_id") not in (None, group_id)):
            self._finish_card()
            self.current = {}
        if group_id and self.current is not None:
            self.current["group_id"] = group_id
            self.current["url"] = f"https://www.toutiao.com/group/{group_id}/"
        if self.current is not None:
            if cr_params.get("title"):
                self.current["title"] = str(cr_params["title"]).strip()
            publication = log_extra.get("createTime") or log_extra.get("publish_time")
            if publication:
                self.current["publish_time"] = str(publication)

        target = None
        if self.current is not None:
            click_data = _json_attribute(attributes.get("data-log-click"))
            if href_match or "l-card-title" in classes or "title" in classes:
                target = "title_text"
            elif tag == "p" or "l-paragraph" in classes or "summary" in classes or "abstract" in classes:
                target = "abstract"
            elif click_data.get("pos") == "author" or "source" in classes:
                target = "source"
            elif tag == "time" or "time" in classes or "date" in classes:
                publication = attributes.get("datetime") or attributes.get("data-time")
                if publication:
                    self.current["publish_time"] = str(publication)
                else:
                    target = "publish_time"
            if tag == "br":
                active_target = next((value for _, value, _ in reversed(self.frames) if value), None)
                if active_target:
                    self._append_text(active_target, " ")
        if tag not in self._VOID_ELEMENTS:
            self.frames.append((tag, target, card_root))

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        target = next((value for _, value, _ in reversed(self.frames) if value), None)
        if target:
            self._append_text(target, data)

    def handle_endtag(self, tag: str) -> None:
        matching_index = next((index for index in range(len(self.frames) - 1, -1, -1) if self.frames[index][0] == tag), None)
        if matching_index is None:
            return
        closes_card = any(frame[2] for frame in self.frames[matching_index:])
        del self.frames[matching_index:]
        if closes_card:
            self._finish_card()

    def close(self) -> None:
        super().close()
        self._finish_card()

    def _finish_card(self) -> None:
        if self.current and not self.current.get("title"):
            self.current["title"] = self.current.get("title_text", "")
        if self.current:
            self.current.pop("title_text", None)
        if self.current and self.current.get("group_id") and self.current.get("title"):
            self.cards.append(self.current)
        self.current = None

    def _append_text(self, target: str, data: str) -> None:
        if self.current is None or not data:
            return
        text = re.sub(r"\s+", " ", data)
        if not text.strip():
            if self.current.get(target) and not self.current[target].endswith(" "):
                self.current[target] += " "
            return
        prefix = " " if data[0].isspace() and self.current.get(target) and not self.current[target].endswith(" ") else ""
        self.current[target] = f"{self.current.get(target, '')}{prefix}{text.strip()}"


def _json_attribute(value) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _object_payload(raw: str) -> dict:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ProviderContractError("provider response must be a JSON object")
    return payload


def _parse_search_dom(dom: str, collected_at: str) -> tuple[HotItem, ...]:
    parser = _SearchDomParser()
    parser.feed(dom)
    parser.close()
    if not parser.cards:
        raise ProviderContractError("toutiao search DOM contained no result cards")
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
