import html
import json
import re
import urllib.request
from collections.abc import Callable
from typing import Any

from src.core_pipeline.source_registry import route_role
from src.core_pipeline.types import HotRecord

BAIDU_TOP_URL = "https://top.baidu.com/board?tab=realtime"


def normalize_dailyhot_response(route: str, payload: dict[str, Any], captured_at: str) -> list[HotRecord]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        rows = []
    records: list[HotRecord] = []
    category = route_role(route)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        records.append(
            HotRecord(
                id=f"hot_{route}_{index:03d}",
                source="dailyhotapi",
                platform=route,
                route=route,
                category=category,
                title=title,
                rank=index,
                hot_value=str(row.get("hot", "")),
                url=str(row.get("url", "")),
                mobile_url=str(row.get("mobileUrl", "")),
                desc=str(row.get("desc", "")),
                author=str(row.get("author", "")),
                cover=str(row.get("cover", "")),
                timestamp=str(row.get("timestamp", "")),
                captured_at=captured_at,
                raw_payload=row,
                fetch_status="ok",
                error_type=None,
            )
        )
    return records


def fetch_dailyhot_route(base_url: str, route: str, timeout_seconds: int = 15) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{route}"
    request = urllib.request.Request(url, headers={"User-Agent": "heatedTopics/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError(f"DailyHotApi route {route} returned non-object JSON")
    return data


def fetch_baidu_top_html(timeout_seconds: int = 15) -> str:
    request = urllib.request.Request(BAIDU_TOP_URL, headers={"User-Agent": "heatedTopics/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_baidu_top_html(page_html: str, captured_at: str) -> list[HotRecord]:
    fragments = re.findall(
        r'<div class="category-wrap_[^"]*.*?(?=<div class="category-wrap_|</main>|$)',
        page_html,
        flags=re.S,
    )
    records: list[HotRecord] = []
    for index, fragment in enumerate(fragments, start=1):
        title = _first_text(fragment, r'<div class="c-single-text-ellipsis">\s*(.*?)\s*</div>')
        if not title:
            continue
        url = _first_attr(fragment, r'<a[^>]+class="title_[^"]*"[^>]+href="([^"]+)"')
        if not url:
            url = _first_attr(fragment, r'<a[^>]+href="([^"]+)"')
        desc = _first_text(fragment, r'<div class="hot-desc_[^"]*large_[^"]*"[^>]*>\s*(.*?)\s*</div>')
        if not desc:
            desc = _first_text(fragment, r'<div class="hot-desc_[^"]*"[^>]*>\s*(.*?)\s*</div>')
        hot_value = _first_text(fragment, r'<div class="hot-index_[^"]*">\s*(.*?)\s*</div>')
        cover = _first_attr(fragment, r'<img[^>]+src="([^"]+)"')
        records.append(
            HotRecord(
                id=f"hot_baidu_{len(records) + 1:03d}",
                source="baidu_top",
                platform="baidu",
                route="baidu",
                category=route_role("baidu"),
                title=title,
                rank=len(records) + 1,
                hot_value=hot_value,
                url=url,
                mobile_url=url,
                desc=desc,
                author="百度热搜",
                cover=cover,
                timestamp="",
                captured_at=captured_at,
                raw_payload={
                    "source_url": BAIDU_TOP_URL,
                    "html_fragment": fragment.strip(),
                },
                fetch_status="ok",
                error_type=None,
            )
        )
    return records


def _dailyhot_records_are_useful(route: str, records: list[HotRecord]) -> bool:
    if route != "baidu":
        return True
    if not records:
        return False
    return any(record.title and "undefined" not in (record.url + record.mobile_url).lower() for record in records)


def _collect_baidu_fallback(captured_at: str, html_fetcher: Callable[[], str]) -> list[HotRecord]:
    return parse_baidu_top_html(html_fetcher(), captured_at)


def _first_text(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S)
    if not match:
        return ""
    text = re.sub(r"<a\b.*?</a>", " ", match.group(1), flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\u200c", "")
    return re.sub(r"\s+", " ", text).strip()


def _first_attr(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def collect_dailyhot_records(
    routes: tuple[str, ...],
    captured_at: str,
    fetcher: Callable[[str], dict[str, Any]],
    baidu_html_fetcher: Callable[[], str] = fetch_baidu_top_html,
    cache_store=None,
    cache_window: str = "today",
) -> list[HotRecord]:
    records: list[HotRecord] = []
    for route in routes:
        try:
            cache_key = f"dailyhot:{route}:{cache_window}"
            cached_rows = cache_store.read(cache_key) if cache_store is not None else None
            if cached_rows is not None:
                if all(isinstance(row, dict) and "record" in row for row in cached_rows):
                    records.extend(HotRecord(**row["record"]) for row in cached_rows)
                    continue
                payload = {"data": [row.get("data", row) for row in cached_rows]}
            else:
                payload = fetcher(route)
            route_records = normalize_dailyhot_response(route, payload, captured_at)
            if not _dailyhot_records_are_useful(route, route_records):
                route_records = _collect_baidu_fallback(captured_at, baidu_html_fetcher)
            if cache_store is not None and cached_rows is None:
                cache_store.write(cache_key, [{"record": record.to_dict()} for record in route_records], fetched_at=captured_at)
            records.extend(route_records)
        except Exception as exc:
            if route == "baidu":
                try:
                    records.extend(_collect_baidu_fallback(captured_at, baidu_html_fetcher))
                    continue
                except Exception:
                    pass
            records.append(
                HotRecord(
                    id=f"hot_{route}_failed",
                    source="dailyhotapi",
                    platform=route,
                    route=route,
                    category=route_role(route),
                    title=f"{route} route failed",
                    rank=0,
                    hot_value="",
                    url="",
                    mobile_url="",
                    desc="",
                    author="",
                    cover="",
                    timestamp="",
                    captured_at=captured_at,
                    raw_payload={},
                    fetch_status="failed",
                    error_type=type(exc).__name__,
                )
            )
    return records
