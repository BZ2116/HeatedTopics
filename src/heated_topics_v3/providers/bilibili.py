"""Bilibili 专栏搜索 + 正文抓取。search 需 WBI 签名；正文取自专栏页
window.__INITIAL_STATE__ 里的 readInfo。"""
from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable

from heated_topics_v3.bilibili_wbi import sign_params
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail

BILIBILI_SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_READ_URL = "https://www.bilibili.com/read/cv"

_EM_RE = re.compile(r"</?em[^>]*>")
_INITIAL_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def build_search_url(
    keyword: str,
    *,
    page: int,
    img_key: str,
    sub_key: str,
    wts: int | None = None,
) -> str:
    params = sign_params(
        {"search_type": "article", "keyword": keyword, "page": page},
        img_key=img_key,
        sub_key=sub_key,
        wts=wts,
    )
    return f"{BILIBILI_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def fetch_bilibili_nav(fetcher: Callable[[str, int], str], timeout_seconds: int = 15) -> dict:
    return json.loads(fetcher(BILIBILI_NAV_URL, timeout_seconds))


def fetch_bilibili_search_text(url: str, fetcher: Callable[[str, int], str], timeout_seconds: int = 20) -> str:
    return fetcher(url, timeout_seconds)


def fetch_bilibili_article_text(cvid: str, fetcher: Callable[[str, int], str], timeout_seconds: int = 20) -> str:
    return fetcher(f"{BILIBILI_READ_URL}{cvid}", timeout_seconds)


def parse_bilibili_search_response(response_text: str, *, source_word: str, fetched_at: str) -> list[HotItem]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    if payload.get("code") not in (0, None):
        return []
    result = payload.get("data", {}).get("result", []) or []
    items: list[HotItem] = []
    for row in result:
        if not isinstance(row, dict):
            continue
        cvid = str(row.get("id", "")).strip()
        raw_title = str(row.get("title", "")).strip()
        if not cvid or not raw_title:
            continue
        title = _EM_RE.sub("", raw_title)
        items.append(
            HotItem(
                item_id=f"bilibili_article_{cvid}",
                platform="bilibili",
                item_type="article",
                title=title,
                url=f"{BILIBILI_READ_URL}{cvid}",
                rank=None,
                heat=HeatMetrics(
                    value=_int_or_none(row.get("view")),
                    label=str(row.get("view", "")),
                    metric_name="article_view",
                    metrics={
                        "views": _int_or_zero(row.get("view")),
                        "likes": _int_or_zero(row.get("like")),
                        "replies": _int_or_zero(row.get("reply")),
                    },
                ),
                summary=str(row.get("desc", "")).strip(),
                category="bilibili_article",
                matched_query_ids=(),
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload={
                    "source_kind": "bilibili_search_recall",
                    "source_path": "B",  # 对齐 Toutiao：B 站无 board 层，全部搜索命中统一标 B
                    "source_word": source_word,
                    "cvid": cvid,
                    "author": str(row.get("author", "")).strip(),
                    "pub_time": row.get("pub_time"),
                },
            )
        )
    return items


def parse_bilibili_article_response(response_text: str, *, item_id: str, item_url: str, fetched_at: str) -> ItemDetail:
    m = _INITIAL_STATE_RE.search(response_text)
    read_info = {}
    if m:
        try:
            state = json.loads(m.group(1))
            read_info = state.get("readInfo", {}) if isinstance(state, dict) else {}
        except json.JSONDecodeError:
            read_info = {}
    content_html = str(read_info.get("content", ""))
    content = _html_to_text(content_html)
    if not content:
        return ItemDetail(
            item_id=item_id, platform="bilibili", url=item_url, title="",
            author="", content="", published_at="", tags=(),
            extraction_method="bilibili_article_view", fetch_status="empty",
            raw_payload={"html_length": len(response_text)},
        )
    author = read_info.get("author", {})
    stats = read_info.get("stats", {})
    return ItemDetail(
        item_id=item_id, platform="bilibili", url=item_url,
        title=str(read_info.get("title", "")).strip(),
        author=str(author.get("name", "")).strip() if isinstance(author, dict) else "",
        content=content, published_at="", tags=(),
        extraction_method="bilibili_article_view", fetch_status="success",
        raw_payload={
            "html_length": len(response_text),
            "views": _int_or_zero(stats.get("view")) if isinstance(stats, dict) else 0,
            "likes": _int_or_zero(stats.get("like")) if isinstance(stats, dict) else 0,
            "coins": _int_or_zero(stats.get("coin")) if isinstance(stats, dict) else 0,
            "favorites": _int_or_zero(stats.get("favorite")) if isinstance(stats, dict) else 0,
        },
    )


def _html_to_text(html: str) -> str:
    text = _TAG_RE.sub("\n", html)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value) -> int:
    v = _int_or_none(value)
    return 0 if v is None else v