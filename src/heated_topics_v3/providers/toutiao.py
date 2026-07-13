"""Toutiao hot-board and single-keyword search provider."""
import asyncio
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Callable, Protocol
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, ProviderContractError, article_text, number_or_none

TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"
TOUTIAO_TIMEZONE = ZoneInfo("Asia/Shanghai")
MIN_ARTICLE_CHARACTERS = 120
MAX_RENDER_CONCURRENCY = 3
TOUTIAO_ARTICLE_EVALUATION_SCRIPT = r"""() => {
    const detailLink = document.querySelector(
        '.block-container .feed-card-article-l a.title, .block-container a[href*="/article/"]'
    );
    const selectors = [
        'article', '.syl-page-article', '.article-content',
        '.feed-card-article-l', '.weitoutiao-html'
    ];
    for (const selector of selectors) {
        const candidates = [...document.querySelectorAll(selector)];
        const texts = candidates.map(node => (node.innerText || '').trim())
            .filter(text => text.length > 80);
        if (texts.length) return {text: texts.join('\n\n'), detail_url: detailLink?.getAttribute('href') || ''};
    }
    return {text: (document.body?.innerText || '').trim(), detail_url: detailLink?.getAttribute('href') || ''};
}"""


class _Renderer(Protocol):
    def fetch(self, url: str) -> str: ...

    def close(self) -> None: ...


class ToutiaoRendererUnavailable(RuntimeError):
    """Raised without sensitive context when browser rendering cannot start."""


class PlaywrightArticleRenderer:
    """One lazy Chromium context shared by bounded concurrent detail requests."""

    def __init__(self, timeout_seconds: int = 20, max_concurrency: int = MAX_RENDER_CONCURRENCY):
        self.timeout_seconds = timeout_seconds
        self.max_concurrency = max_concurrency
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self._closed = False
        self._initialized = False
        self._playwright = None
        self._browser = None
        self._context = None
        self._semaphore = None

    def fetch(self, url: str) -> str:
        self._ensure_started()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(self._fetch(url), self._loop)
        try:
            return future.result(timeout=(self.timeout_seconds * 2) + 20)
        except Exception as error:
            future.cancel()
            if isinstance(error, ToutiaoRendererUnavailable):
                raise
            raise ToutiaoRendererUnavailable(type(error).__name__) from None

    def close(self) -> None:
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
            loop, thread = self._loop, self._thread
        if loop is not None and thread is not None:
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            try:
                future.result(timeout=10)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._closed:
                raise ToutiaoRendererUnavailable("RendererClosed")
            if self._initialized:
                return
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run_loop,
                    name="toutiao-playwright-renderer",
                    daemon=True,
                )
                self._thread.start()
            if not self._ready.wait(timeout=5) or self._loop is None:
                raise ToutiaoRendererUnavailable("EventLoopStartupError")
            future = asyncio.run_coroutine_threadsafe(self._initialize(), self._loop)
            try:
                future.result(timeout=30)
            except Exception as error:
                if isinstance(error, ToutiaoRendererUnavailable):
                    raise
                raise ToutiaoRendererUnavailable(type(error).__name__) from None
            self._initialized = True

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        loop.close()

    async def _initialize(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        except Exception as error:
            await self._shutdown()
            raise ToutiaoRendererUnavailable(type(error).__name__) from None

    async def _fetch(self, url: str) -> str:
        if self._context is None or self._semaphore is None:
            raise ToutiaoRendererUnavailable("RendererNotInitialized")
        async with self._semaphore:
            page = await self._context.new_page()
            try:
                try:
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_seconds * 1000,
                    )
                except Exception:
                    # Toutiao often finishes useful DOM work after a navigation timeout.
                    pass
                try:
                    await page.wait_for_selector(
                        "article, .syl-page-article, .article-content, .feed-card-article-l",
                        timeout=min(8000, self.timeout_seconds * 1000),
                    )
                except Exception:
                    pass
                extracted = await self._evaluate_page(page)
                detail_url = str(extracted.get("detail_url") or "")
                if urlparse(url).path.startswith("/trending/") and detail_url:
                    article_url = urljoin("https://www.toutiao.com/", detail_url)
                    try:
                        await page.goto(
                            article_url,
                            wait_until="domcontentloaded",
                            timeout=self.timeout_seconds * 1000,
                        )
                    except Exception:
                        pass
                    try:
                        await page.wait_for_selector(
                            "article, .syl-page-article, .article-content",
                            timeout=min(8000, self.timeout_seconds * 1000),
                        )
                    except Exception:
                        pass
                    article = await self._evaluate_page(page)
                    article_text = _clean_rendered_article_text(str(article.get("text") or ""))
                    if _is_meaningful_article(article_text):
                        return article_text
                return _clean_rendered_article_text(str(extracted.get("text") or ""))
            finally:
                await page.close()

    @staticmethod
    async def _evaluate_page(page) -> dict[str, str]:
        try:
            value = await page.evaluate(TOUTIAO_ARTICLE_EVALUATION_SCRIPT)
        except Exception:
            raise ToutiaoRendererUnavailable("PageEvaluateError") from None
        return value if isinstance(value, dict) else {"text": str(value or ""), "detail_url": ""}

    async def _shutdown(self) -> None:
        for resource in (self._context, self._browser):
            if resource is not None:
                try:
                    await resource.close()
                except Exception:
                    pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._context = self._browser = self._playwright = None


class ToutiaoProvider:
    def __init__(
        self,
        client: httpx.Client,
        rendered_fetcher: Callable[[str], str] | None = None,
        renderer: _Renderer | None = None,
    ):
        self.client = client
        self._renderer = renderer
        if rendered_fetcher is None:
            self._renderer = renderer or PlaywrightArticleRenderer()
            rendered_fetcher = self._renderer.fetch
        self.rendered_fetcher = rendered_fetcher
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._renderer is not None:
            self._renderer.close()

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
        diagnostic = None
        try:
            content = article_text(self.client.get(item.url).text)
        except Exception:
            content = ""
        method = "toutiao_article_page"
        if not _is_meaningful_article(content) and self.rendered_fetcher:
            method = "toutiao_rendered_page"
            try:
                content = _clean_rendered_article_text(self.rendered_fetcher(item.url))
            except Exception as error:
                diagnostic = (
                    str(error)
                    if isinstance(error, ToutiaoRendererUnavailable)
                    else type(error).__name__
                )
                content = ""
        if not _is_meaningful_article(content):
            if method == "toutiao_rendered_page" and diagnostic is None:
                diagnostic = "RenderedContentTooShort"
            content, method = (item.summary or item.title), ("source_summary" if item.summary else "title")
        return _detail(item, content, collected_at, method, diagnostic)

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

def _clean_rendered_article_text(text: str) -> str:
    navigation = {
        "首页", "关注", "推荐", "搜索", "消息", "发布", "登录", "赞",
        "评论", "收藏", "分享", "打开App", "打开APP", "下载今日头条",
    }
    lines = []
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line in navigation:
            continue
        if re.fullmatch(r"[\d.万亿]+\s*(赞|评论|收藏|分享)?", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _is_meaningful_article(content: str) -> bool:
    cleaned = _clean_rendered_article_text(content)
    return len(cleaned) >= MIN_ARTICLE_CHARACTERS and len(cleaned.splitlines()) >= 2


def _detail(item, content, collected_at, method, diagnostic=None):
    status = "full_text" if method in {"toutiao_article_page", "toutiao_rendered_page"} else ("summary" if method == "source_summary" else "title_only")
    fetch_status = "success" if status == "full_text" else (f"partial:{diagnostic}" if diagnostic else "partial")
    return ItemDetail(item.item_id, content, status, item.publication_time, collected_at, item.url, fetch_status)
