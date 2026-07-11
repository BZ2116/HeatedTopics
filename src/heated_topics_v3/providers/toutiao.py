import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail


TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"


def fetch_toutiao_hot_items(
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
    fetcher=None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    fetch = fetcher or _fetch_text
    return parse_toutiao_hot_board_response(
        fetch(TOUTIAO_HOT_BOARD_URL, timeout_seconds),
        fetched_at=fetched_at,
        matched_query_ids=matched_query_ids,
    )


def parse_toutiao_hot_board_response(
    response_text: str,
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
) -> list[HotItem]:
    payload = json.loads(response_text)
    if payload.get("status") not in ("success", None):
        return []

    items: list[HotItem] = []
    for rank, row in enumerate(payload.get("data", []), start=1):
        row_dict = _dict(row)
        cluster_id = str(row_dict.get("ClusterIdStr") or row_dict.get("ClusterId") or "").strip()
        title = str(row_dict.get("Title") or "").strip()
        url = str(row_dict.get("Url") or "").strip()
        if not cluster_id or not title or not url:
            continue

        hot_value = _int_or_none(row_dict.get("HotValue"))
        category = _category(row_dict)
        items.append(
            HotItem(
                item_id=f"toutiao_{cluster_id}",
                platform="toutiao",
                item_type="topic",
                title=title,
                url=url,
                rank=rank,
                heat=HeatMetrics(
                    value=hot_value,
                    label="" if hot_value is None else str(hot_value),
                    metric_name="hot_value",
                    metrics={} if hot_value is None else {"hot_value": hot_value},
                ),
                summary=str(row_dict.get("QueryWord") or title).strip(),
                category=category,
                matched_query_ids=matched_query_ids,
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload=row_dict,
            )
        )
    return items


def fetch_toutiao_item_detail(item: HotItem, fetcher=None, timeout_seconds: int = 20) -> ItemDetail:
    fetch = fetcher or _fetch_text
    response_text = fetch(item.url, timeout_seconds)
    detail = parse_toutiao_article_page(response_text, item)
    if detail.fetch_status == "success":
        return detail
    return ItemDetail(
        item_id=item.item_id,
        platform=item.platform,
        url=item.url,
        title=item.title,
        author="",
        content=item.summary or item.title,
        published_at="",
        tags=(),
        extraction_method="toutiao_hot_board_payload",
        fetch_status="partial",
        raw_payload=item.raw_payload,
    )


def parse_toutiao_article_page(response_text: str, item: HotItem) -> ItemDetail:
    parser = _ArticleTextParser()
    parser.feed(response_text)
    content = parser.text()
    return ItemDetail(
        item_id=item.item_id,
        platform=item.platform,
        url=item.url,
        title=item.title,
        author="",
        content=content,
        published_at="",
        tags=(),
        extraction_method="toutiao_article_page",
        fetch_status="success" if content else "empty",
        raw_payload={"html_length": len(response_text)},
    )


def _fetch_text(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/html",
            "User-Agent": "Mozilla/5.0 HeatedTopics-V3/0.1",
            "Referer": "https://www.toutiao.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def _category(row: dict[str, Any]) -> str:
    categories = row.get("InterestCategory")
    if isinstance(categories, list) and categories:
        return str(categories[0]).strip()
    return str(row.get("Label") or "").strip()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_article = False
        self._depth = 0
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_article and tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "article":
            self._in_article = True
            self._depth = 1
            return
        if self._in_article:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            if tag in {"script", "style"}:
                self._ignored_depth -= 1
            return
        if self._in_article:
            self._depth -= 1
            if self._depth <= 0:
                self._in_article = False

    def handle_data(self, data: str) -> None:
        if self._in_article and not self._ignored_depth:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)
