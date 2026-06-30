import html
import re
import urllib.request
from pathlib import Path
from collections.abc import Callable
from typing import Any

from src.browser.page_guards import detect_page_guard
from src.core_pipeline.source_registry import route_role
from src.core_pipeline.types import HotRecord


XIAOHONGSHU_EXPLORE_URL = "https://www.xiaohongshu.com/explore"
REBANG_XIAOHONGSHU_URL = "https://rebang.today/?tab=xiaohongshu"
TOPHUB_XIAOHONGSHU_URL = "https://tophub.today/n/L4MdA5ldxD"


def parse_rebang_xiaohongshu_html(page_html: str, captured_at: str, max_items: int = 50) -> list[HotRecord]:
    return _parse_rank_source_html(
        page_html=page_html,
        captured_at=captured_at,
        source="rebang_xiaohongshu",
        source_url=REBANG_XIAOHONGSHU_URL,
        max_items=max_items,
    )


def parse_tophub_xiaohongshu_html(page_html: str, captured_at: str, max_items: int = 50) -> list[HotRecord]:
    return _parse_rank_source_html(
        page_html=page_html,
        captured_at=captured_at,
        source="tophub_xiaohongshu",
        source_url=TOPHUB_XIAOHONGSHU_URL,
        max_items=max_items,
    )


def fetch_xiaohongshu_hot_records(
    captured_at: str,
    http_get: Callable[[str], str] | None = None,
    browser_fetcher: Callable[[str], list[HotRecord]] | None = None,
    rendered_html_fetcher: Callable[[str], str] | None = None,
    max_items: int = 20,
) -> list[HotRecord]:
    if max_items < 1:
        raise ValueError("max_items must be positive")

    actual_http_get = http_get or _fetch_text
    should_try_rendered_html = http_get is None
    sources = [
        (REBANG_XIAOHONGSHU_URL, parse_rebang_xiaohongshu_html),
        (TOPHUB_XIAOHONGSHU_URL, parse_tophub_xiaohongshu_html),
    ]
    for url, parser in sources:
        try:
            records = parser(actual_http_get(url), captured_at, max_items=max_items)
            if records:
                return records
        except Exception:
            pass
        if should_try_rendered_html:
            try:
                fetch_rendered = rendered_html_fetcher or _fetch_rendered_html
                records = parser(fetch_rendered(url), captured_at, max_items=max_items)
                if records:
                    return records
            except Exception:
                pass

    if browser_fetcher is not None:
        return browser_fetcher(captured_at)
    return fetch_xiaohongshu_hot_records_with_browser(captured_at, max_items=max_items)


def rows_to_xiaohongshu_hot_records(
    rows: list[dict[str, Any]],
    captured_at: str,
    raw_payload: dict[str, Any] | None = None,
) -> list[HotRecord]:
    records: list[HotRecord] = []
    for row in rows:
        title = _clean_title(str(row.get("title") or ""))
        content = str(row.get("content") or "").strip()
        author = str(row.get("author") or "").strip()
        if not title:
            title = _title_from_content(content, author=author)
        if not title:
            continue
        rank = len(records) + 1
        records.append(
            HotRecord(
                id=f"hot_xiaohongshu_browser_{rank:03d}",
                source="xiaohongshu_browser",
                platform="xiaohongshu",
                route="xiaohongshu",
                category=route_role("xiaohongshu"),
                title=title,
                rank=rank,
                hot_value=str(row.get("hot_value") or row.get("likes") or ""),
                url=str(row.get("url") or ""),
                mobile_url=str(row.get("url") or ""),
                desc=content,
                author=author,
                cover=str(row.get("cover") or ""),
                timestamp="",
                captured_at=captured_at,
                raw_payload={"row": row, **(raw_payload or {})},
                fetch_status="ok",
                error_type=None,
            )
        )
    return records


def _parse_rank_source_html(
    page_html: str,
    captured_at: str,
    source: str,
    source_url: str,
    max_items: int,
) -> list[HotRecord]:
    table_records = _parse_table_rank_rows(page_html, captured_at, source, source_url, max_items)
    if table_records:
        return table_records

    records: list[HotRecord] = []
    seen_titles: set[str] = set()
    fragments = re.findall(r"<a\b[^>]*>.*?</a>", page_html, flags=re.S | re.I)
    for fragment in fragments:
        title = _first_class_text(fragment, ("title", "t", "name"))
        hot_value = _first_class_text(fragment, ("hot", "heat", "score", "e"))
        rank_text = _first_class_text(fragment, ("rank", "s", "index"))
        href = _first_attr(fragment, r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"']")

        visible_parts = _visible_parts(fragment)
        if not title:
            title = _title_from_visible_parts(visible_parts)
        if not hot_value:
            hot_value = _heat_from_visible_parts(visible_parts)
        if not rank_text and not hot_value:
            continue
        title = _clean_title(title)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        rank = _parse_rank(rank_text) or len(records) + 1
        url = _absolute_url(href, source_url)
        records.append(
            _make_rank_record(
                source=source,
                source_url=source_url,
                captured_at=captured_at,
                index=len(records) + 1,
                rank=rank,
                title=title,
                hot_value=hot_value,
                url=url,
                cover=_first_attr(fragment, r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']"),
                raw_fragment=fragment,
            )
        )
        if len(records) >= max_items:
            break
    return records


def _parse_table_rank_rows(
    page_html: str,
    captured_at: str,
    source: str,
    source_url: str,
    max_items: int,
) -> list[HotRecord]:
    records: list[HotRecord] = []
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", page_html, flags=re.S | re.I)
    for row in rows:
        title_match = re.search(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", row, flags=re.S | re.I)
        if not title_match:
            continue
        url = _absolute_url(title_match.group(1), source_url)
        title = _clean_title(_strip_tags(title_match.group(2)))
        if not title or title == "查看详细":
            continue
        rank_text = _strip_tags(_first_regex(row, r"<td[^>]*align=[\"']center[\"'][^>]*>(.*?)</td>")).rstrip(".")
        hot_value = _strip_tags(_first_regex(row, r"<td[^>]*class=[\"'][^\"']*\bws\b[^\"']*[\"'][^>]*>(.*?)</td>"))
        if not hot_value:
            continue
        records.append(
            _make_rank_record(
                source=source,
                source_url=source_url,
                captured_at=captured_at,
                index=len(records) + 1,
                rank=_parse_rank(rank_text) or len(records) + 1,
                title=title,
                hot_value=hot_value,
                url=url,
                cover=_first_attr(row, r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']"),
                raw_fragment=row,
            )
        )
        if len(records) >= max_items:
            break
    return records


def _make_rank_record(
    source: str,
    source_url: str,
    captured_at: str,
    index: int,
    rank: int,
    title: str,
    hot_value: str,
    url: str,
    cover: str,
    raw_fragment: str,
) -> HotRecord:
    return HotRecord(
        id=f"hot_{source}_{index:03d}",
        source=source,
        platform="xiaohongshu",
        route="xiaohongshu",
        category=route_role("xiaohongshu"),
        title=title,
        rank=rank,
        hot_value=hot_value,
        url=url,
        mobile_url=url,
        desc="",
        author="",
        cover=cover,
        timestamp="",
        captured_at=captured_at,
        raw_payload={
            "source_url": source_url,
            "html_fragment": raw_fragment.strip(),
            "rank_source": source,
        },
        fetch_status="ok",
        error_type=None,
    )


def _fetch_text(url: str, timeout_seconds: int = 15) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _fetch_rendered_html(url: str, timeout_ms: int = 20000, settle_delay_ms: int = 2500) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for rendered Xiaohongshu rank source collection") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(settle_delay_ms)
        content = page.content()
        browser.close()
    return content


def _first_class_text(fragment: str, class_names: tuple[str, ...]) -> str:
    wanted = set(class_names)
    pattern = r"<(?P<tag>[a-z0-9]+)\b[^>]*class=[\"'](?P<class>[^\"']+)[\"'][^>]*>"
    for match in re.finditer(pattern, fragment, flags=re.S | re.I):
        class_tokens = set(re.split(r"\s+", match.group("class").strip()))
        if class_tokens & wanted:
            close_match = re.search(rf"</{re.escape(match.group('tag'))}>", fragment[match.end() :], flags=re.S | re.I)
            if not close_match:
                return ""
            body = fragment[match.end() : match.end() + close_match.start()]
            return _strip_tags(body)
    return ""


def _first_attr(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S | re.I)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _first_regex(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S | re.I)
    if not match:
        return ""
    return match.group(1)


def _visible_parts(fragment: str) -> list[str]:
    text = _strip_tags(fragment)
    return [part for part in re.split(r"\s+", text) if part]


def _strip_tags(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value, flags=re.S | re.I)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\u200c", "")
    return re.sub(r"\s+", " ", text).strip()


def _title_from_visible_parts(parts: list[str]) -> str:
    for part in parts:
        if _parse_rank(part):
            continue
        if _looks_like_heat(part):
            continue
        title = _clean_title(part)
        if title:
            return title
    return ""


def _heat_from_visible_parts(parts: list[str]) -> str:
    for part in reversed(parts):
        if _looks_like_heat(part):
            return part
    return ""


def _looks_like_heat(value: str) -> bool:
    return bool(re.search(r"\d", value)) and bool(re.search(r"(热|万|亿|k|K|w|W|指数|人气|讨论|浏览)", value))


def _parse_rank(value: str) -> int | None:
    match = re.match(r"^\s*(\d{1,3})\s*$", value or "")
    if not match:
        return None
    return int(match.group(1))


def _absolute_url(href: str, source_url: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        base = re.match(r"^(https?://[^/]+)", source_url)
        return f"{base.group(1)}{href}" if base else href
    return href


def fetch_xiaohongshu_hot_records_with_browser(
    captured_at: str,
    browser_state_dir: str | Path = "data/browser_state",
    timeout_ms: int = 20000,
    settle_delay_ms: int = 3000,
    max_items: int = 50,
) -> list[HotRecord]:
    if max_items < 1:
        raise ValueError("max_items must be positive")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for Xiaohongshu hot topic collection") from exc

    state_path = Path(browser_state_dir) / "xiaohongshu.json"
    if not state_path.exists():
        raise RuntimeError(f"Missing browser state for xiaohongshu: {state_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        page.goto(XIAOHONGSHU_EXPLORE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(settle_delay_ms)
        guard = detect_page_guard(page)
        if guard:
            context.close()
            browser.close()
            raise RuntimeError(guard)
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(800)
        rows = _extract_explore_rows(page, max_items=max_items)
        page_text = page.locator("body").inner_text(timeout=timeout_ms)
        current_url = page.url
        context.close()
        browser.close()

    raw_payload = {
        "source_url": XIAOHONGSHU_EXPLORE_URL,
        "current_url": current_url,
        "page_text": page_text,
        "rows_count": len(rows),
    }
    if not rows:
        rows = _rows_from_page_text(page_text, max_items=max_items)
    return rows_to_xiaohongshu_hot_records(rows, captured_at, raw_payload=raw_payload)


def _extract_explore_rows(page, max_items: int) -> list[dict[str, Any]]:
    selectors = [
        "section.note-item",
        ".note-item",
        ".feeds-page .note-item",
        'a[href*="/explore/"]',
    ]
    for selector in selectors:
        rows = page.locator(selector).evaluate_all(
            """
            (elements, maxItems) => elements.slice(0, maxItems).map(element => {
              const text = (element.innerText || '').replace(/\\s+/g, ' ').trim();
              const titleNode = element.querySelector('.title, .note-title, span, a');
              const authorNode = element.querySelector('.author, .name, .username');
              const img = element.querySelector('img');
              const link = element.matches('a[href]') ? element : element.querySelector('a[href]');
              return {
                title: titleNode ? titleNode.innerText.trim() : '',
                content: text,
                author: authorNode ? authorNode.innerText.trim() : '',
                url: link ? link.href : '',
                cover: img ? img.src : '',
              };
            }).filter(row => row.content.length > 0 || row.title.length > 0)
            """,
            max_items,
        )
        if rows:
            return rows[:max_items]
    return []


def _rows_from_page_text(page_text: str, max_items: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in page_text.splitlines():
        title = _clean_title(line)
        if title:
            rows.append({"title": title, "content": line.strip(), "url": ""})
        if len(rows) >= max_items:
            break
    return rows


def _title_from_content(content: str, author: str = "") -> str:
    for line in content.splitlines():
        if author and author in line:
            line = line[: line.find(author)]
        line = re.sub(r"\s+\d+$", "", line).strip()
        title = _clean_title(line)
        if title:
            return title
    text = content
    if author and author in text:
        text = text[: text.find(author)]
    text = re.sub(r"\s+\d+$", "", text).strip()
    return _clean_title(text)


def _clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return ""
    noisy = {"赞", "评论", "收藏", "分享", "关注", "发现", "首页", "购物", "消息", "我"}
    if text in noisy:
        return ""
    if len(text) > 80:
        text = text[:80].rstrip()
    return text
