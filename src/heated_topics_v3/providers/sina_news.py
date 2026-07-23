"""Strict anonymous Sina News hot-list, search, detail and comment provider."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from gne import GeneralNewsExtractor

from heated_topics_v3.content import extract_container_text, validate_full_text
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, ProviderContractError, number_or_none

SINA_HOT_URL = (
    "https://top.news.sina.com.cn/ws/GetTopDataList.php"
    "?js_var=data&top_cat=www_www_all_suda_suda&top_channel=news"
    "&top_order=DESC&top_show_num=50&top_time=today&top_type=day"
)
SINA_SEARCH_URL = "https://search.sina.com.cn/api/news"
SINA_COMMENT_URL = "https://comment5.news.sina.com.cn/page/info"
SINA_SELECTORS = (
    "#artibody", "#article", ".article-content", "#article-content",
    ".article-content-left", ".main-content",
)
SINA_WEIGHTS = {"top_num": 0.70, "comments": 0.30}
SINA_ABSOLUTE_FLOORS = {"comments": 10.0}

SINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_JSONP = re.compile(r"^\s*var\s+\w+\s*=\s*(?P<body>.*?);?\s*$", re.DOTALL)


class SinaNewsProvider:
    platform = "sina_news"
    weights = SINA_WEIGHTS
    absolute_floors = SINA_ABSOLUTE_FLOORS

    def __init__(self, client: httpx.Client):
        self.client = client

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(SINA_HOT_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".txt", self.parse_hot_list(raw, collected_at))

    def search(self, primary_keyword: str, collected_at: str, page: int = 1) -> ProviderCapture:
        response = self.client.get(
            SINA_SEARCH_URL, params={"q": primary_keyword, "page": page}
        )
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".json", self.parse_search(raw, collected_at))

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        try:
            html = self.client.get(item.url).text
        except httpx.HTTPError:
            html = ""
        content = extract_container_text(html, SINA_SELECTORS)
        parser = "sina_dom"
        if validate_full_text(content, item.title, item.summary).status != "accepted":
            try:
                extracted = GeneralNewsExtractor().extract(html)
                content = str(extracted.get("content") or "")
            except Exception:
                content = ""
            parser = "gne"
        validation = validate_full_text(content, item.title, item.summary, parser=parser)
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
        items: Sequence[HotItem],
        collected_at: str,
    ) -> tuple[HotItem, ...]:
        if not items:
            return ()
        enriched: list[HotItem] = []
        for item in items:
            total = self._comment_total(item.raw_payload.get("commentid"))
            if total is None:
                enriched.append(item)
                continue
            metrics = dict(item.heat.metrics)
            metrics["comments"] = total
            enriched.append(
                replace(item, heat=replace(item.heat, metrics=metrics))
            )
        return tuple(enriched)

    def _comment_total(self, commentid: object) -> int | None:
        channel, newsid = _split_commentid(commentid)
        if not channel or not newsid:
            return None
        try:
            response = self.client.get(
                SINA_COMMENT_URL, params={"channel": channel, "newsid": newsid}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        count = (payload.get("result") or {}).get("count") if isinstance(payload.get("result"), dict) else None
        total = number_or_none((count or {}).get("total")) if isinstance(count, dict) else None
        return total

    @staticmethod
    def parse_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        rows = _jsonp_data(raw)
        items = []
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            if not title or not url:
                continue
            top_num = _normalize_top_num(row.get("top_num"))
            metrics = {} if top_num is None else {"top_num": top_num}
            publication = _optional_datetime(row.get("create_date"))
            summary = str(row.get("media") or title)
            items.append(HotItem(
                _item_id(row, url), "sina_news", title, url, rank,
                HeatMetrics(top_num, "" if top_num is None else str(top_num), "top_num", metrics),
                summary,
                publication.isoformat().replace("+00:00", "Z") if publication else None,
                collected_at, row,
            ))
        if not items:
            raise ProviderContractError("sina hot list contained no valid items")
        return tuple(items)

    @staticmethod
    def parse_search(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ProviderContractError("sina search response must be a JSON object")
        result = payload.get("result")
        rows = result.get("data") if isinstance(result, dict) else payload.get("data")
        if not isinstance(rows, list):
            raise ProviderContractError("invalid sina search response")
        items = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            if not title or not url:
                continue
            publication = _optional_datetime(row.get("datetime") or row.get("create_date"))
            summary = str(row.get("intro") or row.get("media") or title)
            items.append(HotItem(
                _item_id(row, url), "sina_news", title, url, None,
                HeatMetrics(None, "", "top_num", {}),
                summary,
                publication.isoformat().replace("+00:00", "Z") if publication else None,
                collected_at, row,
            ))
        return tuple(items)


def _jsonp_data(raw: str) -> list:
    match = _JSONP.match(raw or "")
    if not match:
        raise ProviderContractError("sina hot list is not a JSONP assignment")
    try:
        payload = json.loads(match.group("body"))
    except (TypeError, ValueError):
        raise ProviderContractError("sina hot list body is not valid JSON") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise ProviderContractError("sina hot list data must be a non-empty list")
    return data


def _normalize_top_num(value: object) -> int | None:
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    return number_or_none(value)


def _split_commentid(commentid: object) -> tuple[str, str]:
    text = str(commentid or "")
    if ":" not in text:
        return "", ""
    channel, _, newsid = text.partition(":")
    return channel.strip(), newsid.strip()


def _item_id(row: dict, url: str) -> str:
    commentid = str(row.get("commentid") or "")
    _, newsid = _split_commentid(commentid)
    key = newsid or re.sub(r"\W+", "", url.rsplit("/", 1)[-1]) or re.sub(r"\W+", "", url)
    return f"sina_news_{key}"


def _optional_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=SINA_TIMEZONE).astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SINA_TIMEZONE)
    return parsed.astimezone(timezone.utc)
