import asyncio
import html
import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail, TopicQuery


TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"
TOUTIAO_ARTICLE_INFO_URL = "https://m.toutiao.com/i{article_id}/info/"
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
    rendered_search_fetcher=None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    fetch = fetcher or _fetch_text
    rendered_fetch = rendered_search_fetcher or _fetch_toutiao_rendered_search_links
    items: list[HotItem] = []
    for phrase in phrases:
        url = f"{TOUTIAO_SEARCH_URL}?{urlencode(_search_params(phrase))}"
        parsed_items = parse_toutiao_search_response(fetch(url, timeout_seconds), phrase, fetched_at)
        if _needs_rendered_search(parsed_items):
            rendered_items = parse_toutiao_rendered_search_links(
                rendered_fetch(phrase, timeout_seconds),
                phrase,
                fetched_at,
            )
            if rendered_items:
                items.extend(rendered_items)
                continue
        items.extend(parsed_items)
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


def parse_toutiao_rendered_search_links(
    links: list[dict[str, Any]],
    phrase: str,
    fetched_at: str,
) -> list[HotItem]:
    results: list[_SearchResult] = []
    seen_urls: set[str] = set()
    for link in links:
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        url = resolve_toutiao_content_url(href)
        if not _is_content_url(url):
            continue
        canonical_url = _canonical_url(url)
        if canonical_url in seen_urls:
            continue
        text = _clean_multiline_text(str(link.get("text") or ""))
        card_text = _clean_multiline_text(str(link.get("card") or ""))
        title = _first_nonempty_line(text) or _first_nonempty_line(card_text)
        if not title:
            continue
        summary = _summary_from_rendered_card(card_text, title)
        results.append(_SearchResult(title=title, url=url, text=f"{title}\n{summary}".strip()))
        seen_urls.add(canonical_url)

    items: list[HotItem] = []
    total_count = len(results)
    for rank, result in enumerate(results, start=1):
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
                    "source_kind": "rendered_search_result",
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
                raw_payload={**row_dict, "source_kind": "hot_board"},
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


def fetch_toutiao_item_details(
    items: list[HotItem],
    fetcher=None,
    timeout_seconds: int = 20,
    rendered_texts_fetcher=None,
) -> list[ItemDetail]:
    fetch = fetcher or _fetch_text
    rendered_fetch = rendered_texts_fetcher or (None if fetcher is not None else _fetch_toutiao_rendered_article_texts)
    details: list[ItemDetail | None] = []
    render_queue: list[tuple[int, HotItem, str]] = []

    for item in items:
        detail_url = resolve_toutiao_content_url(item.url)
        response_text = fetch(detail_url, timeout_seconds)
        detail = parse_toutiao_article_page(response_text, item)
        if detail.fetch_status == "success":
            details.append(detail)
            continue

        details.append(None)
        if rendered_fetch and _is_content_url(detail_url):
            render_queue.append((len(details) - 1, item, detail_url))

    rendered_contents: dict[str, str] = {}
    if render_queue and rendered_fetch:
        rendered_contents = rendered_fetch(tuple(detail_url for _, _, detail_url in render_queue), timeout_seconds)

    for index, item, detail_url in render_queue:
        rendered_content = rendered_contents.get(detail_url, "")
        if rendered_content:
            details[index] = _rendered_detail(item, detail_url, rendered_content)

    return [
        detail if detail is not None else _partial_detail(item)
        for detail, item in zip(details, items, strict=True)
    ]


def fetch_toutiao_item_detail(
    item: HotItem,
    fetcher=None,
    timeout_seconds: int = 20,
    rendered_text_fetcher=None,
) -> ItemDetail:
    rendered_texts_fetcher = None
    if rendered_text_fetcher is not None:
        rendered_texts_fetcher = lambda urls, timeout: {
            url: rendered_text_fetcher(url, timeout) for url in urls
        }
    return fetch_toutiao_item_details(
        [item],
        fetcher=fetcher,
        timeout_seconds=timeout_seconds,
        rendered_texts_fetcher=rendered_texts_fetcher,
    )[0]


def _rendered_detail(item: HotItem, detail_url: str, content: str) -> ItemDetail:
    return ItemDetail(
        item_id=item.item_id,
        platform=item.platform,
        url=detail_url,
        title=item.title,
        author="",
        content=content,
        published_at="",
        tags=(),
        extraction_method="toutiao_rendered_page",
        fetch_status="success",
        raw_payload={"source_url": item.url, "content_url": detail_url},
    )


def _partial_detail(item: HotItem) -> ItemDetail:
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


def resolve_toutiao_content_url(url: str) -> str:
    absolute_url = html.unescape(_absolute_url(url.strip()))
    parsed = urlparse(absolute_url)
    if not parsed.path.startswith("/search/jump"):
        return absolute_url

    outer_url = parse_qs(parsed.query).get("url", [""])[0]
    if not outer_url:
        return absolute_url
    nested_url = parse_qs(urlparse(outer_url).query).get("h5_url", [""])[0]
    return html.unescape(nested_url or outer_url)


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


def _needs_rendered_search(items: list[HotItem]) -> bool:
    if not items:
        return False
    return all(item.raw_payload.get("source_kind") == "search_keyword_hit" for item in items)


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
    match = re.search(r"/(?:article|trending|group)/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"(?:groupid|item_id|search_result_id)=(\d+)", url)
    return "" if not match else match.group(1)


def _is_content_url(url: str) -> bool:
    return (
        url.startswith("/search/jump")
        or "so.toutiao.com/search/jump" in url
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


def _clean_multiline_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _first_nonempty_line(value: str) -> str:
    for line in value.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _summary_from_rendered_card(card_text: str, title: str) -> str:
    for line in card_text.splitlines():
        candidate = line.strip()
        if candidate and candidate != title:
            return candidate
    return title


def _fetch_toutiao_rendered_search_links(phrase: str, timeout_seconds: int) -> list[dict[str, str]]:
    return asyncio.run(_fetch_toutiao_rendered_search_links_async(phrase, timeout_seconds))


async def _fetch_toutiao_rendered_search_links_async(
    phrase: str,
    timeout_seconds: int,
) -> list[dict[str, str]]:
    from playwright.async_api import async_playwright

    url = f"{TOUTIAO_SEARCH_URL}?{urlencode({key: value for key, value in _search_params(phrase).items() if key != 'format'})}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return await page.evaluate(
                """() => Array.from(document.querySelectorAll('a')).map((a) => ({
                    text: (a.innerText || a.textContent || '').trim(),
                    href: a.href,
                    card: (
                        a.closest('[class*=result], [class*=card], [class*=item], li, section, article, div')
                        ?.innerText || ''
                    ).trim(),
                })).filter((item) => item.href && item.href.includes('/search/jump'))"""
            )
        finally:
            await browser.close()


def _fetch_toutiao_rendered_article_text(url: str, timeout_seconds: int) -> str:
    return _fetch_toutiao_rendered_article_texts((url,), timeout_seconds).get(url, "")


def _fetch_toutiao_rendered_article_texts(urls: tuple[str, ...], timeout_seconds: int) -> dict[str, str]:
    return asyncio.run(_fetch_toutiao_rendered_article_texts_async(urls, timeout_seconds))


async def _fetch_toutiao_rendered_article_texts_async(
    urls: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, str]:
    from playwright.async_api import async_playwright

    contents: dict[str, str] = {}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        try:
            for url in urls:
                page = await context.new_page()
                try:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_selector(
                            "article, .syl-page-article, .article-content",
                            timeout=8000,
                        )
                    except Exception:
                        pass
                    text = await page.evaluate(
                        """() => {
                            const selectors = ['article', '.syl-page-article', '.article-content'];
                            for (const selector of selectors) {
                                const element = document.querySelector(selector);
                                const text = (element?.innerText || '').trim();
                                if (text.length > 80) return text;
                            }
                            return (document.body?.innerText || '').trim();
                        }"""
                    )
                    contents[url] = _clean_rendered_article_text(text)
                finally:
                    await page.close()
            return contents
        finally:
            await browser.close()


def _clean_rendered_article_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    drop_prefixes = {
        "关注",
        "推荐",
        "搜索",
        "消息",
        "发布",
        "登录",
        "赞",
        "评论",
        "收藏",
        "分享",
    }
    filtered = [line for line in lines if line not in drop_prefixes]
    return "\n".join(filtered).strip()


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


# ---------------------------------------------------------------------------
# Article info enrichment (mobile info API)
# ---------------------------------------------------------------------------


ARTICLE_HEAT_WEIGHTS: dict[str, int] = {
    "impression_count": 1,
    "digg_count": 2,
    "comment_count": 5,
    "repost_count": 10,
    "repin_count": 3,
}


def extract_toutiao_article_id(url: str) -> str | None:
    """Extract numeric article id from a Toutiao article URL. Returns None on miss."""
    if not url:
        return None
    match = re.search(r"/(?:article|trending|group)/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"(?:groupid|item_id|search_result_id)=(\d+)", url)
    return match.group(1) if match else None


def compute_article_heat(metrics: dict[str, int | None]) -> int:
    """Weighted composite of mobile info API metrics."""
    total = 0
    for key, weight in ARTICLE_HEAT_WEIGHTS.items():
        value = metrics.get(key)
        if value is None:
            continue
        try:
            total += int(value) * weight
        except (TypeError, ValueError):
            continue
    return total


def fetch_toutiao_article_info(
    article_id: str,
    fetcher: Callable[[str, int], str] | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any] | None:
    """Fetch the mobile article info endpoint. Returns the inner `data` dict or None."""
    fetch = fetcher or _fetch_text
    url = TOUTIAO_ARTICLE_INFO_URL.format(article_id=article_id)
    try:
        response = fetch(url, timeout_seconds)
    except Exception:
        return None
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def attach_article_heat_fields(
    item: HotItem, info: dict[str, Any] | None,
) -> HotItem:
    """Return a new HotItem with article_heat / is_toutiao_hot / etc. merged into raw_payload.

    Hot board items keep their hot_value (do NOT overwrite); search items get
    hot_value=article_heat so downstream scoring can treat them uniformly.
    """
    raw_payload = dict(item.raw_payload)
    if info is None:
        raw_payload["article_info_status"] = "fetch_failed"
        return _replace_item(item, raw_payload=raw_payload)

    raw_counts = {
        "impression_count": _safe_int(info.get("impression_count")),
        "digg_count": _safe_int(info.get("digg_count")),
        "comment_count": _safe_int(info.get("comment_count")),
        "repost_count": _safe_int(info.get("repost_count")),
        "repin_count": _safe_int(info.get("repin_count")),
    }
    article_heat = compute_article_heat(raw_counts)
    is_toutiao_hot = bool(info.get("is_toutiao_hot"))
    is_original = bool(info.get("is_original"))
    content_html = str(info.get("content") or "")

    was_hot_board = item.raw_payload.get("source_kind") in {
        "hot_board", "search_hot_board_overlap",
    }

    raw_payload["article_heat"] = article_heat
    raw_payload["raw_counts"] = raw_counts
    raw_payload["is_toutiao_hot"] = is_toutiao_hot
    raw_payload["is_original"] = is_original
    raw_payload["content_html"] = content_html
    raw_payload["article_info_status"] = "ok"

    new_heat = item.heat
    new_source_kind = item.raw_payload.get("source_kind", "article_info")
    if was_hot_board:
        raw_payload["metric_name"] = "hot_value+article_heat"
    else:
        new_source_kind = "article_info"
        raw_payload["source_kind"] = new_source_kind
        raw_payload["metric_name"] = "article_heat"
        new_heat = HeatMetrics(
            value=article_heat,
            label=str(article_heat),
            metric_name="article_heat",
            metrics={key: value for key, value in raw_counts.items() if value is not None},
        )

    return _replace_item(
        item,
        raw_payload=raw_payload,
        heat=new_heat,
        raw_payload_source_kind=new_source_kind,
    )


def _replace_item(
    item: HotItem,
    *,
    raw_payload: dict[str, Any] | None = None,
    heat: HeatMetrics | None = None,
    raw_payload_source_kind: str | None = None,
) -> HotItem:
    """Replace selected fields on a frozen HotItem."""
    from dataclasses import replace as dc_replace

    updates: dict[str, Any] = {}
    if raw_payload is not None:
        updates["raw_payload"] = raw_payload
    if heat is not None:
        updates["heat"] = heat
    if raw_payload_source_kind is not None:
        rp = updates.get("raw_payload", item.raw_payload)
        rp = dict(rp)
        rp["source_kind"] = raw_payload_source_kind
        updates["raw_payload"] = rp
    return dc_replace(item, **updates)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_toutiao_search_pages(
    phrase: str,
    *,
    fetched_at: str,
    max_pages: int = 1,
    per_page: int = 10,
    fetcher: Callable[[str, int], str] | None = None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    """Paginated search. Dedupes by canonical URL and article_id across pages.

    Returns the combined list of HotItems from all pages.
    """
    fetch = fetcher or _fetch_text
    seen_urls: set[str] = set()
    seen_article_ids: set[str] = set()
    merged: list[HotItem] = []
    for page in range(max(1, max_pages)):
        offset = page * per_page
        params = _search_params(phrase) | {"count": str(per_page), "offset": str(offset)}
        url = f"{TOUTIAO_SEARCH_URL}?{urlencode(params)}"
        try:
            response = fetch(url, timeout_seconds)
        except Exception:
            break
        page_items = parse_toutiao_search_response(response, phrase, fetched_at)
        if not page_items:
            break
        for item in page_items:
            if not _is_content_url(item.url):
                continue
            canonical = _canonical_url(item.url)
            if canonical in seen_urls:
                continue
            seen_urls.add(canonical)
            aid = extract_toutiao_article_id(item.url)
            if aid:
                if aid in seen_article_ids:
                    continue
                seen_article_ids.add(aid)
            merged.append(item)
    return merged
