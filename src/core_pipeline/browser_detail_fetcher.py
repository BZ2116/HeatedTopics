import urllib.parse
from pathlib import Path

from src.browser.page_guards import detect_page_guard
from src.core_pipeline.providers.weibo import extract_weibo_posts_from_text
from src.core_pipeline.providers.xiaohongshu import extract_xiaohongshu_notes_from_text


DEFAULT_SETTLE_DELAY_MS = 2500

SEARCH_URLS = {
    "weibo": "https://s.weibo.com/weibo?q={query}",
    "xiaohongshu": "https://www.xiaohongshu.com/search_result?keyword={query}",
}

STATE_FILES = {
    "weibo": "weibo.json",
    "xiaohongshu": "xiaohongshu.json",
}


def build_platform_search_url(platform: str, query: str) -> str:
    if platform not in SEARCH_URLS:
        raise ValueError(f"Unsupported detail platform: {platform}")
    return SEARCH_URLS[platform].format(query=urllib.parse.quote(query))


def fetch_social_details_with_browser(
    platform: str,
    query: str,
    browser_state_dir: str | Path = "data/browser_state",
    timeout_ms: int = 20000,
    settle_delay_ms: int = DEFAULT_SETTLE_DELAY_MS,
) -> list[dict[str, object]]:
    if settle_delay_ms < 0:
        raise ValueError("settle_delay_ms must be non-negative")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for Weibo/Xiaohongshu detail collection") from exc

    state_path = Path(browser_state_dir) / STATE_FILES[platform]
    if not state_path.exists():
        raise RuntimeError(f"Missing browser state for {platform}: {state_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        page.goto(build_platform_search_url(platform, query), wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(settle_delay_ms)
        guard = detect_page_guard(page)
        if guard:
            context.close()
            browser.close()
            raise RuntimeError(guard)
        dom_rows = _extract_dom_rows(page, platform)
        page_text = page.locator("body").inner_text(timeout=timeout_ms)
        current_url = page.url
        context.close()
        browser.close()

    if dom_rows:
        return [_with_url(row, current_url) for row in dom_rows]
    if platform == "weibo":
        rows = extract_weibo_posts_from_text(page_text)
    elif platform == "xiaohongshu":
        rows = extract_xiaohongshu_notes_from_text(page_text)
    else:
        raise ValueError(f"Unsupported detail platform: {platform}")
    return [_with_url(row, current_url) for row in rows]


def _with_url(row: dict[str, object], url: str) -> dict[str, object]:
    if row.get("url"):
        return row
    return {**row, "url": url}


def _extract_dom_rows(page, platform: str) -> list[dict[str, object]]:
    selectors = {
        "weibo": [
            'div.card-wrap[action-type="feed_list_item"]',
            'div[action-type="feed_list_item"]',
            ".card-wrap",
        ],
        "xiaohongshu": [
            "section.note-item",
            ".note-item",
            ".feeds-page .note-item",
        ],
    }[platform]
    for selector in selectors:
        rows = page.locator(selector).evaluate_all(
            """
            elements => elements.slice(0, 8).map(element => {
              const text = (element.innerText || '').replace(/\\s+/g, ' ').trim();
              const link = element.querySelector('a[href]');
              const href = link ? link.href : '';
              return { content: text, comments_preview: [], url: href };
            }).filter(row => row.content.length > 20)
            """
        )
        if rows:
            return rows[:5]
    return []

