import json
import urllib.request
from collections.abc import Callable
from typing import Any

from heated_topics_v3.contracts import HeatMetrics, HotItem


JUEJIN_HOT_RANK_URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"


def fetch_juejin_hot_items(
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
    fetcher: Callable[[str, int], str] | None = None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    fetch = fetcher or _fetch_text
    return parse_juejin_rank_response(
        fetch(JUEJIN_HOT_RANK_URL, timeout_seconds),
        fetched_at=fetched_at,
        matched_query_ids=matched_query_ids,
    )


def parse_juejin_rank_response(
    response_text: str,
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
) -> list[HotItem]:
    payload = json.loads(response_text)
    if payload.get("err_no") not in (0, None):
        return []

    items: list[HotItem] = []
    for rank, row in enumerate(payload.get("data", []), start=1):
        content = _dict(row.get("content"))
        counter = _dict(row.get("content_counter"))
        content_id = str(content.get("content_id", "")).strip()
        title = str(content.get("title", "")).strip()
        if not content_id or not title:
            continue

        hot_rank = _int_or_none(counter.get("hot_rank"))
        item = HotItem(
            item_id=f"juejin_{content_id}",
            platform="juejin",
            item_type="article",
            title=title,
            url=f"https://juejin.cn/post/{content_id}",
            rank=rank,
            heat=HeatMetrics(
                value=hot_rank,
                label="" if hot_rank is None else str(hot_rank),
                metric_name="hot_rank",
                metrics={
                    "views": _int_or_zero(counter.get("view")),
                    "likes": _int_or_zero(counter.get("like")),
                    "collects": _int_or_zero(counter.get("collect")),
                    "comments": _int_or_zero(counter.get("comment_count")),
                    "interactions": _int_or_zero(counter.get("interact_count")),
                },
            ),
            summary=str(content.get("brief", "")).strip(),
            category=str(content.get("category_id", "")).strip(),
            matched_query_ids=matched_query_ids,
            fetched_at=fetched_at,
            fetch_status="success",
            raw_payload=row,
        )
        items.append(item)
    return items


def _fetch_text(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 HeatedTopics-V3/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return 0 if parsed is None else parsed
