"""Map last30days Item dicts to V3 HotItem + ItemDetail.

# Field mapping reference (verified against last30days-skill-cn v3.2.0
# scripts/lib/schema.py + actual `--emit json` stdout output):
#
# last30days top-level JSON shape:
#   {
#     "topic": str,
#     "range": {"from": ISO-date, "to": ISO-date},
#     "generated_at": ISO-datetime,
#     "mode": str,
#     "<platform>": [Item, ...],   # one list per platform
#     "best_practices": [...],
#     "prompt_pack": [...]
#   }
#   Top-level platform keys (per schema.py): weibo, xiaohongshu, bilibili,
#   zhihu, douyin, wechat, baidu, toutiao. Each is a list of Item dicts.
#   (Not wrapped in a "results" array.)
#
# Per-platform Item shape (each has id, engagement, relevance, why_relevant,
# subs {relevance, recency, engagement}, score, cross_refs):
#
#   WeiboItem (top-level key "weibo"):
#     id, text, url, author_handle, author_id?, date?, date_confidence,
#     engagement {views, likes, comments, reposts, ...}
#
#   XiaohongshuItem (top-level key "xiaohongshu"):
#     id, title, desc, url, author_name, author_id?, date?, date_confidence,
#     engagement, hashtags
#
#   BilibiliItem (top-level key "bilibili"):
#     id, title, url, bvid, channel_name, author_mid?, date?, date_confidence,
#     engagement {views, danmaku, likes, ...}, description, duration?
#
#   ZhihuItem (top-level key "zhihu"):
#     id, title, excerpt, url, author, date?, date_confidence, content_type,
#     engagement {voteups, num_comments, collects, ...}
#
#   DouyinItem (top-level key "douyin"):
#     id, text, url, author_name, author_id?, date?, date_confidence,
#     engagement, hashtags, duration?
#
#   WechatItem (top-level key "wechat"):
#     id, title, summary, url, account_name, date?
#     (engagement shape varies; treated as pass-through)
#
#   BaiduItem (top-level key "baidu"):
#     id, title, abstract, snippet, url, source_domain?, source?, date?
#
#   ToutiaoItem (top-level key "toutiao"):
#     id, title, content?, abstract?, url, source?, date?, author?
#
# Notes:
# - last30days `--fetch-bodies` enables full body fetch where supported
#   (Weibo/Zhihu/Bilibili fully; XHS/Douyin need login = empty body;
#    WeChat/Baidu/Toutiao partial). Body absence is expected, not an error.
# - last30days per-item `score` is last30days's own weighted composite
#   (relevance 45 + recency 25 + engagement 30) — NOT used as V3 rank.
#   V3 rank comes from per-platform position in the result list.
# - V3 HotItem requires (item_id, platform, title, url, rank, heat, summary).
#   V3 ItemDetail requires (item_id, content, content_status,
#   publication_time, collected_at, source_url, fetch_status).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from heated_topics_v3.clock import SHANGHAI
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail

# last30days top-level platform keys we know how to map.
_PLATFORM_KEYS: tuple[str, ...] = (
    "weibo", "xiaohongshu", "bilibili", "zhihu",
    "douyin", "wechat", "baidu", "toutiao",
)


def _engagement_to_metrics(eng: Any) -> dict[str, int | float]:
    """Filter last30days engagement dict to int/float values for HeatMetrics."""
    if not isinstance(eng, dict):
        return {}
    out: dict[str, int | float] = {}
    for key, value in eng.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[key] = value
    return out


def _dominant_metric(metrics: dict[str, int | float]) -> tuple[int | float, str]:
    """Pick the single best engagement value for HeatMetrics.value + label."""
    for candidate in ("views", "voteups", "likes", "score"):
        if metrics.get(candidate):
            return metrics[candidate], candidate
    if metrics:
        first_key = next(iter(metrics))
        return metrics[first_key], first_key
    return 0, "engagement"


def _now_iso() -> str:
    """Current Shanghai time as ISO-8601 string for collected_at."""
    return datetime.now(tz=SHANGHAI).isoformat(timespec="seconds")


# ---- Per-platform extractors -----------------------------------------------
# Each takes a raw last30days item dict and returns a tuple of
# (item_id, title, body, summary, author_name) or None to skip.


def _extract_weibo(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    text = (raw.get("text") or "").strip()
    if not text:
        return None
    rid = str(raw.get("id") or "").strip()
    return (
        f"weibo:{rid}",
        text[:80] or "(无标题)",
        text,
        text[:200],
        str(raw.get("author_handle") or ""),
    )


def _extract_xiaohongshu(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    title = (raw.get("title") or "").strip()
    desc = (raw.get("desc") or "").strip()
    if not title and not desc:
        return None
    rid = str(raw.get("id") or "").strip()
    return (
        f"xiaohongshu:{rid}",
        title or desc[:80],
        desc,
        f"{title}\n{desc[:200]}".strip(),
        str(raw.get("author_name") or ""),
    )


def _extract_bilibili(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    rid = str(raw.get("bvid") or raw.get("id") or "").strip()
    return (
        f"bilibili:{rid}",
        title,
        str(raw.get("description") or ""),
        title,
        str(raw.get("channel_name") or ""),
    )


def _extract_zhihu(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    title = (raw.get("title") or "").strip()
    excerpt = (raw.get("excerpt") or "").strip()
    if not title and not excerpt:
        return None
    rid = str(raw.get("id") or "").strip()
    return (
        f"zhihu:{rid}",
        title or excerpt[:80],
        excerpt,
        f"{title}\n{excerpt[:200]}".strip(),
        str(raw.get("author") or ""),
    )


def _extract_douyin(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    text = (raw.get("text") or "").strip()
    if not text:
        return None
    rid = str(raw.get("id") or "").strip()
    return (
        f"douyin:{rid}",
        text[:80] or "(无标题)",
        text,
        text[:200],
        str(raw.get("author_name") or ""),
    )


def _extract_wechat(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    rid = str(raw.get("id") or "").strip()
    body = str(raw.get("content") or "")
    summary = str(raw.get("summary") or title)
    author = str(raw.get("author") or raw.get("account_name") or "")
    return (f"wechat:{rid}", title, body, summary, author)


def _extract_baidu(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    rid = str(raw.get("id") or "").strip()
    body = str(raw.get("content") or "")
    summary = str(raw.get("abstract") or title)
    author = str(raw.get("source") or raw.get("source_domain") or "")
    return (f"baidu:{rid}", title, body, summary, author)


def _extract_toutiao(raw: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    rid = str(raw.get("id") or "").strip()
    body = str(raw.get("content") or raw.get("abstract") or "")
    summary = str(raw.get("abstract") or title)
    author = str(raw.get("source") or raw.get("author") or "")
    return (f"toutiao:{rid}", title, body, summary, author)


_PLATFORM_EXTRACTORS: dict[str, Callable[[dict[str, Any]], tuple[str, str, str, str, str] | None]] = {
    "weibo": _extract_weibo,
    "xiaohongshu": _extract_xiaohongshu,
    "bilibili": _extract_bilibili,
    "zhihu": _extract_zhihu,
    "douyin": _extract_douyin,
    "wechat": _extract_wechat,
    "baidu": _extract_baidu,
    "toutiao": _extract_toutiao,
}


def to_hot_items(
    report: dict[str, Any],
) -> tuple[list[HotItem], list[ItemDetail]]:
    """Convert a parsed last30days report into V3 (HotItem, ItemDetail) pairs.

    Iterates top-level platform keys in `_PLATFORM_KEYS` order. Rank is the
    1-based position within each platform's item list. Items missing
    required fields are skipped silently.
    """
    items: list[HotItem] = []
    details: list[ItemDetail] = []
    now = _now_iso()

    for platform in _PLATFORM_KEYS:
        raw_items = report.get(platform)
        if not isinstance(raw_items, list):
            continue
        extractor = _PLATFORM_EXTRACTORS[platform]
        for rank, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, dict):
                continue
            extracted = extractor(raw)
            if extracted is None:
                continue
            item_id, title, body, summary, _author = extracted
            metrics = _engagement_to_metrics(raw.get("engagement"))
            value, label = _dominant_metric(metrics)
            heat = HeatMetrics(
                value=value,
                label=label,
                metric_name="last30days_engagement",
                metrics=metrics,
            )
            item = HotItem(
                item_id=item_id,
                platform=platform,
                title=title,
                url=str(raw.get("url") or ""),
                rank=rank,
                heat=heat,
                summary=summary,
                publication_time=raw.get("date"),
                collected_at=now,
                raw_payload=dict(raw),
            )
            detail = ItemDetail(
                item_id=item_id,
                content=body,
                content_status="full_text" if body else "title_only",
                publication_time=raw.get("date"),
                collected_at=now,
                source_url=str(raw.get("url") or ""),
                fetch_status="ok" if body else "title_only",
                metadata={"source": "last30days", "platform": platform},
            )
            items.append(item)
            details.append(detail)

    return items, details
