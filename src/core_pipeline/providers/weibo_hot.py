import re
import urllib.parse
from pathlib import Path
from typing import Any

from src.browser.page_guards import detect_page_guard
from src.core_pipeline.source_registry import route_role
from src.core_pipeline.types import HotRecord


WEIBO_HOT_URL = "https://s.weibo.com/top/summary?cate=realtimehot"


def rows_to_weibo_hot_records(
    rows: list[dict[str, Any]],
    captured_at: str,
    raw_payload: dict[str, Any] | None = None,
) -> list[HotRecord]:
    records: list[HotRecord] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        rank = int(row.get("rank") or len(records) + 1)
        url = str(row.get("url") or build_weibo_search_url(title))
        records.append(
            HotRecord(
                id=f"hot_weibo_browser_{len(records) + 1:03d}",
                source="weibo_browser_hot",
                platform="weibo",
                route="weibo",
                category=route_role("weibo"),
                title=title,
                rank=rank,
                hot_value=str(row.get("hot_value") or ""),
                url=url,
                mobile_url=url,
                desc="",
                author="微博热搜",
                cover="",
                timestamp="",
                captured_at=captured_at,
                raw_payload={"row": row, **(raw_payload or {})},
                fetch_status="ok",
                error_type=None,
            )
        )
    return records


def build_weibo_search_url(title: str) -> str:
    return f"https://s.weibo.com/weibo?q={urllib.parse.quote(title)}"


def parse_weibo_hot_text(page_text: str, captured_at: str, max_items: int = 50) -> list[HotRecord]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in page_text.splitlines():
        text = re.sub(r"\s+", " ", line).strip()
        match = re.match(r"^(?P<rank>\d{1,2})\s+(?P<title>.+?)\s+(?P<hot>\d{4,})\b", text)
        if not match:
            continue
        title = match.group("title").strip()
        if title in seen:
            continue
        seen.add(title)
        rows.append(
            {
                "rank": int(match.group("rank")),
                "title": title,
                "hot_value": match.group("hot"),
                "url": build_weibo_search_url(title),
            }
        )
        if len(rows) >= max_items:
            break
    return rows_to_weibo_hot_records(rows, captured_at, {"source_url": WEIBO_HOT_URL, "page_text": page_text})


def fetch_weibo_hot_records_with_browser(
    captured_at: str,
    browser_state_dir: str | Path = "data/browser_state",
    timeout_ms: int = 20000,
    settle_delay_ms: int = 2500,
    max_items: int = 50,
) -> list[HotRecord]:
    if max_items < 1:
        raise ValueError("max_items must be positive")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for Weibo hot topic collection") from exc

    state_path = Path(browser_state_dir) / "weibo.json"
    if not state_path.exists():
        raise RuntimeError(f"Missing browser state for weibo: {state_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        page.goto(WEIBO_HOT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(settle_delay_ms)
        guard = detect_page_guard(page)
        if guard:
            context.close()
            browser.close()
            raise RuntimeError(guard)
        page_text = page.locator("body").inner_text(timeout=timeout_ms)
        current_url = page.url
        context.close()
        browser.close()
    return parse_weibo_hot_text(page_text, captured_at, max_items=max_items) or rows_to_weibo_hot_records(
        [],
        captured_at,
        {"source_url": WEIBO_HOT_URL, "current_url": current_url, "page_text": page_text},
    )
