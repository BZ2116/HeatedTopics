import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener, urlopen

from src.demo_config import DAILY_HOT_API_BASES, TOP_N_PER_PLATFORM
from src.hot_topic_types import HotRecord


@dataclass(frozen=True)
class FetchIssue:
    platform: str
    url: str
    error: str


def fetch_json(url: str, timeout: int = 12) -> dict[str, Any]:
    host = urlparse(url).hostname
    opener = build_opener(ProxyHandler({})) if host in {"localhost", "127.0.0.1", "::1"} else None
    open_url = opener.open if opener else urlopen
    with open_url(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def daily_hot_api_bases() -> list[str]:
    configured = os.getenv("DAILY_HOT_API_BASES") or os.getenv("DAILY_HOT_API_BASE")
    if configured:
        return [base.strip().rstrip("/") for base in configured.split(",") if base.strip()]
    return [base.rstrip("/") for base in DAILY_HOT_API_BASES]


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        for key in ("data", "list", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    if isinstance(data, list):
        return data
    return []


def normalize_item(platform: str, index: int, item: dict[str, Any], crawl_time: str) -> HotRecord:
    title = str(item.get("title") or item.get("name") or item.get("word") or "").strip()
    hot = str(item.get("hot") or item.get("desc") or item.get("heat") or item.get("views") or "")
    url = str(item.get("url") or item.get("mobilUrl") or item.get("mobileUrl") or item.get("link") or "")
    rank = int(item.get("rank") or index + 1)
    return HotRecord(
        platform=platform,
        rank=rank,
        title=title,
        hot=hot,
        url=url,
        crawl_time=crawl_time,
    )


def fetch_platform(
    platform: str,
    limit: int = TOP_N_PER_PLATFORM,
    api_bases: list[str] | None = None,
    fetcher=fetch_json,
    issues: list[FetchIssue] | None = None,
) -> list[HotRecord]:
    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bases = api_bases or daily_hot_api_bases()

    for base in bases:
        url = f"{base.rstrip('/')}/{platform}"
        try:
            payload = fetcher(url)
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            if issues is not None:
                issues.append(FetchIssue(platform=platform, url=url, error=str(exc)))
            continue

        records = []
        for index, item in enumerate(extract_items(payload)[:limit]):
            if not isinstance(item, dict):
                continue
            record = normalize_item(platform, index, item, crawl_time)
            if record.title:
                records.append(record)

        if records:
            return records

        if issues is not None:
            issues.append(FetchIssue(platform=platform, url=url, error="empty data"))

    return []


def fetch_all_platforms(
    platforms: list[str],
    limit: int = TOP_N_PER_PLATFORM,
    api_bases: list[str] | None = None,
    return_issues: bool = False,
):
    records: list[HotRecord] = []
    issues: list[FetchIssue] = []
    for platform in platforms:
        records.extend(fetch_platform(platform, limit=limit, api_bases=api_bases, issues=issues))
    if return_issues:
        return records, issues
    return records
