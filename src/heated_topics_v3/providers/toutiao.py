import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail, TopicQuery


TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"
TOUTIAO_QUERY_ALIASES = {
    "AI Agent": ("AI智能体", "智能体", "人工智能", "大模型"),
    "Claude Code": ("Claude Code AI编程", "AI编程", "编程助手", "代码生成"),
    "OpenAI": ("人工智能", "大模型"),
    "MCP": ("MCP 协议",),
    "RAG": ("检索增强生成", "知识库问答", "大模型知识库"),
    "Cursor": ("Cursor AI编程", "AI编程", "编程助手", "代码生成"),
}


def build_toutiao_search_phrases(queries: tuple[TopicQuery, ...]) -> tuple[str, ...]:
    phrases: list[str] = []
    for query in queries:
        _append_unique(phrases, query.query)
        for keyword in query.keywords:
            _append_unique(phrases, keyword)
            for alias in TOUTIAO_QUERY_ALIASES.get(keyword, ()):
                _append_unique(phrases, alias)
    return tuple(phrases)


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


def fetch_toutiao_search_items(
    phrases: tuple[str, ...],
    fetched_at: str,
    fetcher=None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    fetch = fetcher or _fetch_text
    items: list[HotItem] = []
    for phrase in phrases:
        url = f"{TOUTIAO_SEARCH_URL}?{urlencode(_search_params(phrase))}"
        items.extend(parse_toutiao_search_response(fetch(url, timeout_seconds), phrase, fetched_at))
    return items


def parse_toutiao_search_response(response_text: str, phrase: str, fetched_at: str) -> list[HotItem]:
    payload = json.loads(response_text)
    dom = str(payload.get("dom") or "")
    parser = _SearchResultParser()
    parser.feed(dom)
    parser.close()
    total_count = _int_or_none(payload.get("count")) or len(parser.results)
    if total_count > 0 and not parser.results:
        return [_keyword_hit_item(phrase, total_count, fetched_at, payload)]
    items: list[HotItem] = []
    for rank, result in enumerate(parser.results, start=1):
        if not _is_content_url(result.url):
            continue
        heat_value, metric_name, metrics, strength = _search_heat(result.text, total_count, rank)
        article_id = _article_id_from_url(result.url) or f"{_slug(phrase)}_{rank}"
        items.append(
            HotItem(
                item_id=f"toutiao_search_{article_id}",
                platform="toutiao",
                item_type="search_result",
                title=result.title,
                url=result.url,
                rank=rank,
                heat=HeatMetrics(
                    value=heat_value,
                    label="" if heat_value is None else str(heat_value),
                    metric_name=metric_name,
                    metrics=metrics,
                ),
                summary=result.summary,
                category="search",
                matched_query_ids=(),
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload={
                    "search_phrase": phrase,
                    "alias_for": _alias_for(phrase),
                    "source_kind": "search_result",
                    "heat_signal_strength": strength,
                    "text": result.text,
                },
            )
        )
    return items


def _keyword_hit_item(
    phrase: str,
    total_count: int,
    fetched_at: str,
    payload: dict[str, Any],
) -> HotItem:
    heat_value = max(total_count, 1)
    return HotItem(
        item_id=f"toutiao_search_keyword_{_slug(phrase)}",
        platform="toutiao",
        item_type="search_result",
        title=phrase,
        url=f"{TOUTIAO_SEARCH_URL}?{urlencode(_search_params(phrase))}",
        rank=1,
        heat=HeatMetrics(
            value=heat_value,
            label=str(heat_value),
            metric_name="search_rank",
            metrics={"search_rank": heat_value},
        ),
        summary=phrase,
        category="search",
        matched_query_ids=(),
        fetched_at=fetched_at,
        fetch_status="partial",
        raw_payload={
            "search_phrase": phrase,
            "alias_for": _alias_for(phrase),
            "source_kind": "search_keyword_hit",
            "heat_signal_strength": "weak",
            "result_count": total_count,
            "raw_payload_keys": sorted(payload.keys()),
        },
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


def merge_toutiao_items(search_items: list[HotItem], hot_board_items: list[HotItem]) -> list[HotItem]:
    hot_board_by_url = {_canonical_url(item.url): item for item in hot_board_items}
    merged: list[HotItem] = []
    seen_urls: set[str] = set()
    for search_item in search_items:
        canonical_url = _merge_key(search_item)
        if canonical_url in seen_urls:
            continue
        hot_board_item = hot_board_by_url.get(canonical_url)
        if hot_board_item is None:
            merged.append(search_item)
        else:
            raw_payload = {
                **search_item.raw_payload,
                "source_kind": "search_hot_board_overlap",
                "heat_signal_strength": "strong",
                "hot_board_payload": hot_board_item.raw_payload,
            }
            merged.append(
                HotItem(
                    item_id=search_item.item_id,
                    platform=search_item.platform,
                    item_type=search_item.item_type,
                    title=search_item.title,
                    url=search_item.url,
                    rank=search_item.rank,
                    heat=hot_board_item.heat,
                    summary=search_item.summary,
                    category=search_item.category,
                    matched_query_ids=search_item.matched_query_ids,
                    fetched_at=search_item.fetched_at,
                    fetch_status=search_item.fetch_status,
                    raw_payload=raw_payload,
                )
            )
        seen_urls.add(canonical_url)
    return merged


def fetch_toutiao_item_detail(item: HotItem, fetcher=None, timeout_seconds: int = 20) -> ItemDetail:
    fetch = fetcher or _fetch_text
    response_text = fetch(_absolute_url(item.url), timeout_seconds)
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


def _absolute_url(url: str) -> str:
    if url.startswith("/"):
        return f"https://so.toutiao.com{url}"
    return url


def _search_params(phrase: str) -> dict[str, str]:
    return {
        "keyword": phrase,
        "pd": "information",
        "source": "search_subtab_switch",
        "from": "information",
        "format": "json",
        "count": "10",
        "offset": "0",
    }


def _alias_for(phrase: str) -> str:
    for keyword, aliases in TOUTIAO_QUERY_ALIASES.items():
        if phrase in aliases:
            return keyword
    return ""


def _search_heat(text: str, total_count: int, rank: int) -> tuple[int | None, str, dict[str, int], str]:
    hot_value = _metric_from_text(text, "热度")
    if hot_value is not None:
        return hot_value, "search_heat", {"hot_value": hot_value}, "medium"

    metrics: dict[str, int] = {}
    reads = _metric_from_text(text, "阅读")
    comments = _metric_from_text(text, "评论")
    if reads is not None:
        metrics["reads"] = reads
    if comments is not None:
        metrics["comments"] = comments
    if metrics:
        return sum(metrics.values()), "search_engagement", metrics, "medium"

    weak_value = max(total_count - rank + 1, 1)
    return weak_value, "search_rank", {"search_rank": weak_value}, "weak"


def _metric_from_text(text: str, label: str) -> int | None:
    match = re.search(rf"{label}\s*([0-9.]+)\s*(万)?", text)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2) == "万":
        value *= 10000
    return int(value)


def _article_id_from_url(url: str) -> str:
    match = re.search(r"/(?:article|trending)/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"(?:groupid|item_id|search_result_id)=(\d+)", url)
    return "" if not match else match.group(1)


def _is_content_url(url: str) -> bool:
    return (
        url.startswith("/search/jump")
        or "toutiao.com/article/" in url
        or "toutiao.com/trending/" in url
        or "toutiao.com/group/" in url
    )


def _canonical_url(url: str) -> str:
    return url.split("?", maxsplit=1)[0].rstrip("/")


def _merge_key(item: HotItem) -> str:
    if item.raw_payload.get("source_kind") == "search_keyword_hit" or item.url.startswith("/search/jump"):
        return item.item_id
    return _canonical_url(item.url)


def _slug(value: str) -> str:
    return re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_").lower() or "keyword"


def _category(row: dict[str, Any]) -> str:
    categories = row.get("InterestCategory")
    if isinstance(categories, list) and categories:
        return str(categories[0]).strip()
    return str(row.get("Label") or "").strip()


def _append_unique(values: list[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in values:
        values.append(normalized)


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


class _SearchResult:
    def __init__(self, title: str, url: str, text: str) -> None:
        self.title = title
        self.url = url
        self.text = text

    @property
    def summary(self) -> str:
        parts = [part.strip() for part in self.text.split("\n") if part.strip()]
        for part in parts:
            if part != self.title and not any(label in part for label in ("阅读", "评论", "热度")):
                return part
        return self.title


class _SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[_SearchResult] = []
        self._active_href = ""
        self._active_title_parts: list[str] = []
        self._collect_text = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and attrs_dict.get("href"):
            self._flush_result()
            self._active_href = str(attrs_dict["href"])
            self._active_title_parts = []
            self._collect_text = True
        elif self._active_href:
            self._collect_text = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_href:
            title = " ".join(part for part in self._active_title_parts if part).strip()
            if title:
                self._parts.append(title)

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text or not self._collect_text:
            return
        if self._active_href and not self._parts:
            self._active_title_parts.append(text)
        self._parts.append(text)

    def close(self) -> None:
        self._flush_result()
        super().close()

    def _flush_result(self) -> None:
        title = " ".join(part for part in self._active_title_parts if part).strip()
        text = "\n".join(self._parts).strip()
        if title and self._active_href:
            self.results.append(_SearchResult(title=title, url=self._active_href, text=text))
        self._active_href = ""
        self._active_title_parts = []
        self._parts = []
        self._collect_text = False
