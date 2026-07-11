import json
import re
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail


JUEJIN_HOT_RANK_URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
JUEJIN_ARTICLE_DETAIL_URL = "https://api.juejin.cn/content_api/v1/article/detail"


def fetch_juejin_hot_items(
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
    fetcher: Callable[[str, int], str] | None = None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    fetch = fetcher or _fetch_text
    return parse_juejin_rank_response(
        fetch(JUEJIN_HOT_RANK_URL, timeout_seconds),
        fetched_at=fetched_at,
        matched_query_ids=matched_query_ids,
    )


def fetch_juejin_item_detail(
    item: HotItem,
    fetcher: Callable[[str, int, dict[str, str] | None], str] | None = None,
    timeout_seconds: int = 20,
) -> ItemDetail:
    fetch = fetcher or _fetch_text_with_optional_json_body
    article_id = _article_id_from_item(item)

    api_response = fetch(JUEJIN_ARTICLE_DETAIL_URL, timeout_seconds, {"article_id": article_id})
    detail = parse_juejin_detail_response(api_response, item)
    if detail.fetch_status == "success":
        return detail

    article_url = f"https://juejin.cn/post/{article_id}"
    html_response = fetch(article_url, timeout_seconds, None)
    return parse_juejin_article_page(html_response, item)


def parse_juejin_rank_response(
    response_text: str,
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
) -> list[HotItem]:
    payload = json.loads(response_text)
    if payload.get("err_no") not in (0, None):
        return []

    items: list[HotItem] = []
    for rank, row in enumerate(payload.get("data", []), start=1):
        content = _dict(row.get("content"))
        counter = _dict(row.get("content_counter"))
        content_id = str(content.get("content_id", "")).strip()
        title = str(content.get("title", "")).strip()
        if not content_id or not title:
            continue

        hot_rank = _int_or_none(counter.get("hot_rank"))
        item = HotItem(
            item_id=f"juejin_{content_id}",
            platform="juejin",
            item_type="article",
            title=title,
            url=f"https://juejin.cn/post/{content_id}",
            rank=rank,
            heat=HeatMetrics(
                value=hot_rank,
                label="" if hot_rank is None else str(hot_rank),
                metric_name="hot_rank",
                metrics={
                    "views": _int_or_zero(counter.get("view")),
                    "likes": _int_or_zero(counter.get("like")),
                    "collects": _int_or_zero(counter.get("collect")),
                    "comments": _int_or_zero(counter.get("comment_count")),
                    "interactions": _int_or_zero(counter.get("interact_count")),
                },
            ),
            summary=str(content.get("brief", "")).strip(),
            category=str(content.get("category_id", "")).strip(),
            matched_query_ids=matched_query_ids,
            fetched_at=fetched_at,
            fetch_status="success",
            raw_payload=row,
        )
        items.append(item)
    return items


def parse_juejin_detail_response(response_text: str, item: HotItem) -> ItemDetail:
    payload = json.loads(response_text)
    data = _dict(payload.get("data"))
    article_info = _dict(data.get("article_info"))
    content = str(
        article_info.get("mark_content")
        or article_info.get("content")
        or article_info.get("brief_content")
        or ""
    ).strip()
    if payload.get("err_no") not in (0, None) or not content:
        return _empty_detail(item, "juejin_detail_api", payload)

    author = _dict(data.get("author_user_info"))
    return ItemDetail(
        item_id=item.item_id,
        platform=item.platform,
        url=item.url,
        title=str(article_info.get("title") or item.title).strip(),
        author=str(author.get("user_name") or author.get("name") or "").strip(),
        content=content,
        published_at=str(article_info.get("ctime") or "").strip(),
        tags=tuple(
            str(tag.get("tag_name", "")).strip()
            for tag in data.get("tags", [])
            if isinstance(tag, dict) and str(tag.get("tag_name", "")).strip()
        ),
        extraction_method="juejin_detail_api",
        fetch_status="success",
        raw_payload=payload,
    )


def parse_juejin_article_page(response_text: str, item: HotItem) -> ItemDetail:
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
        extraction_method="juejin_article_page",
        fetch_status="success" if content else "empty",
        raw_payload={"html_length": len(response_text)},
    )


def _fetch_text(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 HeatedTopics-V3/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _fetch_text_with_optional_json_body(
    url: str,
    timeout_seconds: int,
    body: dict[str, str] | None = None,
) -> str:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "application/json, text/html",
        "User-Agent": "Mozilla/5.0 HeatedTopics-V3/0.1",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _article_id_from_item(item: HotItem) -> str:
    raw_content = _dict(item.raw_payload.get("content"))
    content_id = str(raw_content.get("content_id") or "").strip()
    if content_id:
        return content_id
    return re.sub(r"^juejin_", "", item.item_id)


def _empty_detail(item: HotItem, extraction_method: str, raw_payload: dict[str, Any]) -> ItemDetail:
    return ItemDetail(
        item_id=item.item_id,
        platform=item.platform,
        url=item.url,
        title=item.title,
        author="",
        content="",
        published_at="",
        tags=(),
        extraction_method=extraction_method,
        fetch_status="empty",
        raw_payload=raw_payload,
    )


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
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return 0 if parsed is None else parsed
