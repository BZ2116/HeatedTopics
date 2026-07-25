"""Anonymous Sina News hot list, search, article, and comment provider.

Pure parsers — no I/O. Network access is owned by callers (cache layer / CLI).
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

from heated_topics_v3.contracts import HeatMetrics, HotItem

SINA_HOT_URL = (
    "https://top.news.sina.com.cn/ws/GetTopDataList.php"
    "?js_var=data&top_cat=www_www_all_suda_suda&top_channel=news"
    "&top_order=DESC&top_show_num=50&top_time=today&top_type=day"
)
SINA_SEARCH_URL = "https://search.sina.com.cn/api/news"
SINA_COMMENT_URL = "https://comment5.news.sina.com.cn/page/info"

SINA_TIMEZONE = timezone(timedelta(hours=8))
_JSONP_RE = re.compile(r"^\s*var\s+\w+\s*=\s*(?P<body>.*?);?\s*$", re.DOTALL)
_ARTICLE_SELECTORS = (
    "#artibody",
    "#article",
    ".article-content",
    "#article-content",
    ".article-content-left",
    ".main-content",
)


# ---------------------------------------------------------------------------
# Hot list
# ---------------------------------------------------------------------------

def parse_sina_hot_response(raw: str, fetched_at: str) -> tuple[HotItem, ...]:
    payload = _decode_jsonp(raw)
    if not isinstance(payload, dict):
        raise ValueError("sina hot list root must be an object")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError("sina hot list data must be a non-empty list")
    items: list[HotItem] = []
    for rank, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        top_num = _normalize_int(row.get("top_num"))
        metrics: dict[str, int] = {} if top_num is None else {"top_num": top_num}
        publication = _parse_sina_datetime(
            row.get("create_date"), row.get("create_time")
        )
        items.append(
            HotItem(
                item_id=_sina_hot_item_id(row, url),
                platform="sina_news",
                item_type="news",
                title=title,
                url=url,
                rank=rank,
                heat=HeatMetrics(
                    value=top_num,
                    label="" if top_num is None else str(top_num),
                    metric_name="top_num",
                    metrics=metrics,
                ),
                summary=str(row.get("media") or title),
                category=str(row.get("cat_name") or ""),
                matched_query_ids=(),
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload=row,
                publication_time=publication,
            )
        )
    if not items:
        raise ValueError("sina hot list produced no valid items")
    return tuple(items)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def parse_sina_search_response(raw: str, fetched_at: str) -> tuple[HotItem, ...]:
    payload = _load_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("sina search response must be a JSON object")
    if payload.get("code") not in (0, "0", 200, "200"):
        raise ValueError(f"sina search response code != 0 ({payload.get('code')})")
    rows = _sina_search_rows(payload)
    if rows is None:
        raise ValueError("sina search response missing data.list")
    items: list[HotItem] = []
    for rank, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        dataid = str(row.get("dataid") or "").strip()
        items.append(
            HotItem(
                item_id=_sina_search_item_id(row, url, dataid),
                platform="sina_news",
                item_type="news",
                title=title,
                url=url,
                rank=None,
                heat=HeatMetrics(
                    value=None, label="", metric_name="search_rank", metrics={}
                ),
                summary=str(row.get("media_show") or row.get("source") or title),
                category="",
                matched_query_ids=(),
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload=row,
                publication_time=None,
            )
        )
    return tuple(items)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def parse_sina_comments_response(raw: str) -> int | None:
    """Extract the public comment total from a sina comments payload.

    Returns None on any mismatch — the public comment endpoint is unreliable
    and sina surfaces ad-hoc "code: 4" errors for missing message boards.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    if isinstance(status, dict) and status.get("code") not in (0, "0", 200, "200"):
        return None
    count = result.get("count")
    if not isinstance(count, dict):
        return None
    total = _coerce_int(count.get("total"))
    if total is None:
        total = _coerce_int(count.get("total_reply"))
    return total


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

def parse_sina_article_response(
    raw: str, title: str = "", summary: str = ""
) -> str:
    """Extract the article body text from a sina article HTML page.

    Returns "" when the input is empty or the page contains no extractable text.
    """
    if not raw or not raw.strip():
        return ""
    text = _extract_article_text(raw)
    return _normalize_whitespace(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_jsonp(raw: str) -> Any:
    if not raw or not raw.strip():
        raise ValueError("sina response is empty")
    match = _JSONP_RE.match(raw)
    if not match:
        raise ValueError("sina response is not a JSONP assignment")
    try:
        return json.loads(match.group("body"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"sina JSONP body is not valid JSON: {exc}") from exc


def _load_json(raw: str) -> Any:
    if not raw or not raw.strip():
        raise ValueError("sina response is empty")
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"sina response is not valid JSON: {exc}") from exc


def _sina_search_rows(payload: dict) -> list | None:
    """Sina search returns rows under data.list."""
    data = payload.get("data")
    if isinstance(data, dict):
        items = data.get("list")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    return None


def _sina_hot_item_id(row: dict, url: str) -> str:
    ext4 = str(row.get("ext4") or "").strip()
    if ext4:
        return f"sina_news_{ext4}"
    # Fallback: extract path slug from URL
    slug = url.rsplit("/", 1)[-1].split(".", 1)[0]
    clean = re.sub(r"\W+", "", slug)
    return f"sina_news_{clean}" if clean else f"sina_news_{abs(hash(url)) & 0xFFFFFFFF:x}"


def _sina_search_item_id(row: dict, url: str, dataid: str) -> str:
    if dataid:
        clean = re.sub(r"\W+", "_", dataid).strip("_")
        if clean:
            return f"sina_news_{clean}"
    ext4 = str(row.get("ext4") or "").strip()
    if ext4:
        return f"sina_news_{ext4}"
    slug = url.rsplit("/", 1)[-1].split(".", 1)[0]
    clean = re.sub(r"\W+", "", slug)
    return f"sina_news_{clean}" if clean else f"sina_news_{abs(hash(url)) & 0xFFFFFFFF:x}"


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def _parse_sina_datetime(date_str: Any, time_str: Any) -> str | None:
    d = str(date_str or "").strip()
    t = str(time_str or "").strip()
    if not d:
        return None
    if not t:
        t = "00:00:00"
    text = f"{d} {t}"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return (
            parsed.replace(tzinfo=SINA_TIMEZONE)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return None


def _article_text_from_html(html: str) -> str:
    """Pull the article body from a sina news article page.

    Strategy: walk the DOM with HTMLParser. Whenever a <div> opens whose class
    attribute contains one of _ARTICLE_CLASS_TOKENS, push a fresh capture frame
    onto a stack (so the innermost matching div wins). Whenever that div closes,
    finalize the frame and pop it. Return the richest match that yields
    >= _RICH_THRESHOLD_CHARS characters. Falls back to all-paragraph harvest
    from the cleaned page when nothing rich was found.
    """
    cleaned = _strip_junk_blocks(html)
    parser = _SinaArticleParser(_ARTICLE_CLASS_TOKENS)
    parser.feed(cleaned)
    candidates = parser.rich_candidates(_RICH_THRESHOLD_CHARS)
    if candidates:
        return _normalize_whitespace("\n".join(candidates[0]))
    paragraphs = _paragraphs_from_html(cleaned)
    return _normalize_whitespace("\n".join(paragraphs))


class _SinaArticleParser(HTMLParser):
    """DOM walker that tracks every matching <div> via a stack of capture frames.

    Each frame owns its own paragraph buffer. Writing to ``self._parts`` always
    targets the top frame. When a frame's owning <div> closes, its buffer is
    finalized into ``self._captures``. This naturally produces a list of
    captured regions ordered by document position; the deepest (last) one that
    crosses the richness threshold wins.
    """

    def __init__(self, tokens: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self._tokens = tokens
        self._ignored_stack: list[str] = []
        # Stack of capture frames. Each frame is the current owner of
        # self._parts while it is on top. Frames below the top stay paused.
        self._frames: list[dict] = []
        self._parts: list[str] = []
        self._captures: list[str] = []

    def _class_matches(self, attrs: list[tuple[str, str | None]]) -> bool:
        cls = ""
        for k, v in attrs:
            if k == "class" and v:
                cls = v.lower()
                break
        return any(t in cls for t in self._tokens)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._ignored_stack.append(tag)
            return
        if tag == "div":
            if self._class_matches(attrs):
                # Open a new frame; becomes the active owner of self._parts.
                self._frames.append({"parts": self._parts, "buffer": [], "matched": True})
                self._parts = self._frames[-1]["buffer"]
            else:
                # Non-matching div: push a sentinel frame so we balance closes.
                self._frames.append({"parts": self._parts, "buffer": [], "matched": False})
                self._parts = self._frames[-1]["buffer"]

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_stack:
            if self._ignored_stack[-1] == tag:
                self._ignored_stack.pop()
            else:
                # mismatched, ignore
                return
            return
        if tag != "div":
            # Only div opens/closes shift the frame stack; other tags simply
            # flush text into the active frame's buffer.
            if self._frames:
                text = " ".join(self._parts).strip()
                if text:
                    self._frames[-1]["buffer"].append(text)
                self._parts = []
            return
        if not self._frames:
            return
        # Closing a div: flush remaining text into this frame, finalize, pop.
        frame = self._frames.pop()
        text = " ".join(self._parts).strip()
        if text:
            frame["buffer"].append(text)
        self._parts = frame["parts"]  # restore caller's buffer
        if frame["matched"]:
            joined = "\n".join(p for p in frame["buffer"] if p)
            if joined.strip():
                self._captures.append(joined)

    def handle_data(self, data: str) -> None:
        if self._ignored_stack or not self._frames:
            return
        text = " ".join(data.split())
        if text:
            self._parts.append(text)

    @property
    def captures(self) -> list[str]:
        return self._captures

    def rich_candidates(self, threshold: int) -> list[list[str]]:
        out: list[list[str]] = []
        for joined in self._captures:
            parts = [p for p in joined.split("\n") if p]
            if sum(len(p) for p in parts) >= threshold:
                out.append(parts)
        # Order by richness descending so the body wins over the bare title.
        out.sort(key=lambda parts: sum(len(p) for p in parts), reverse=True)
        return out


# ---------------------------------------------------------------------------
# Article — public shim + helpers
# ---------------------------------------------------------------------------

_ARTICLE_CLASS_TOKENS = (
    "article-content-left",
    "article-content",
    "artibody",
    "article",
    "main-content",
)
_RICH_THRESHOLD_CHARS = 200


def _extract_article_text(html: str) -> str:
    cleaned = _strip_junk_blocks(html)
    return _article_text_from_html(cleaned)


_JUNK_BLOCK_RE = re.compile(
    r"<(script|style|ins|iframe|noscript|svg)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)


def _strip_junk_blocks(html: str) -> str:
    if not html:
        return ""
    return _JUNK_BLOCK_RE.sub("", html)


def _paragraphs_from_html(html: str) -> list[str]:
    segments = re.split(r"</?(?:p|div|br|section|article)[^>]*>", html, flags=re.IGNORECASE)
    out: list[str] = []
    for seg in segments:
        text = _strip_all_tags(seg)
        text = _normalize_whitespace(text)
        if text and len(text) >= 4:
            out.append(text)
    return out


class _TagStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        return "".join(self._chunks)


def _strip_all_tags(html: str) -> str:
    stripper = _TagStripper()
    try:
        stripper.feed(html)
    except Exception:
        return ""
    return stripper.text


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\t\r]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def enrich_sina_with_comments(
    items: tuple[HotItem, ...],
    fetcher,
    timeout_seconds: int = 15,
) -> tuple[HotItem, ...]:
    """Optionally enrich items with their public comment count.

    `fetcher` is a Callable[[str, int, dict], str] that takes a URL, timeout,
    and a params dict, returning the response body. Returns items unchanged
    when no item carries a commentid.
    """
    if not items:
        return items
    enriched: list[HotItem] = []
    for item in items:
        dataid = str(item.raw_payload.get("dataid") or "").strip()
        if not dataid or ":" not in dataid:
            enriched.append(item)
            continue
        channel, _, newsid = dataid.partition(":")
        url = SINA_COMMENT_URL
        try:
            raw = fetcher(url, timeout_seconds, {"channel": channel, "newsid": newsid})
        except Exception:
            enriched.append(item)
            continue
        total = parse_sina_comments_response(raw)
        if total is None:
            enriched.append(item)
            continue
        metrics = dict(item.heat.metrics)
        metrics["comments"] = total
        enriched.append(
            replace(item, heat=replace(item.heat, metrics=metrics))
        )
    return tuple(enriched)
