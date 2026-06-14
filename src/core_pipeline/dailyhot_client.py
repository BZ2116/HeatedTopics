import json
import urllib.request
from typing import Any

from src.core_pipeline.source_registry import route_role
from src.core_pipeline.types import HotRecord


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