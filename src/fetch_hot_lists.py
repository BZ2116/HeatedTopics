import json
from datetime import datetime
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from src.demo_config import DAILY_HOT_API_BASE, TOP_N_PER_PLATFORM
from src.hot_topic_types import HotRecord


def fetch_json(url: str, timeout: int = 12) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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


def fetch_platform(platform: str, limit: int = TOP_N_PER_PLATFORM) -> list[HotRecord]:
    url = f"{DAILY_HOT_API_BASE}/{platform}"
    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        payload = fetch_json(url)
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []

    records = []
    for index, item in enumerate(extract_items(payload)[:limit]):
        if not isinstance(item, dict):
            continue
        record = normalize_item(platform, index, item, crawl_time)
        if record.title:
            records.append(record)
    return records


def fetch_all_platforms(platforms: list[str], limit: int = TOP_N_PER_PLATFORM) -> list[HotRecord]:
    records: list[HotRecord] = []
    for platform in platforms:
        records.extend(fetch_platform(platform, limit=limit))
    return records