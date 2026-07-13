# Deprecated: this standalone experiment is retained only for historical comparison.
# Use `python -m heated_topics_v3.cli toutiao --profile-v2 ...` for maintained runs.
# New collection, scoring, caching, and output changes belong in `src/heated_topics_v3/`.

"""
Toutiao HotValue filtering demo.

Standalone script. Does not import the main heated_topics_v3 package.
Goal: validate whether HotValue from the hot board can be used as a filter
for profile-relevant content.

Stage 1: fetch hot board + search DOM (lightweight)
Stage 2: for each search result, fetch the mobile article info endpoint
         (https://m.toutiao.com/i{id}/info/) which returns impression_count,
         comment_count, digg_count, repost_count, repin_count and full content.
Stage 3: composite article_heat score + threshold sweep.

Run:
    python demos/toutiao_heat_filter/demo.py
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import math
import os
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlencode, urlparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
SEARCH_URL = "https://so.toutiao.com/search/"
ARTICLE_INFO_URL_TEMPLATE = "https://m.toutiao.com/i{article_id}/info/"

# Hard-coded profile queries (kept separate from main package config).
# Each entry: (query_id, phrase, alias_for_keyword)
PROFILE_QUERIES: tuple[tuple[str, str, str], ...] = (
    ("q1", "AI Agent", "AI Agent"),
    ("q2", "AI智能体", "AI Agent"),
    ("q3", "人工智能", "AI Agent"),
    ("q4", "Claude Code", "Claude Code"),
    ("q5", "MCP 协议", "MCP"),
    ("q6", "RAG", "RAG"),
)

# Candidate thresholds for the two distinct scales:
#   hot_value (hot board):       150K - 20M range
#   article_heat (article info): typically tens to thousands
HOT_VALUE_THRESHOLDS: tuple[int, ...] = (500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000)
ARTICLE_HEAT_THRESHOLDS: tuple[int, ...] = (50, 200, 500, 1_000, 5_000, 20_000)

# Composite weights inspired by Toutiao's "阅读/评论/分享加权求和" guidance.
# These are demo defaults; real Toutiao weights are proprietary.
ARTICLE_HEAT_WEIGHTS: dict[str, int] = {
    "impression_count": 1,
    "digg_count": 2,
    "comment_count": 5,
    "repost_count": 10,
    "repin_count": 3,
}

# Alias expansion for hot-board matching (and optionally search).
# When a user submits one of these keywords, we also try all of its aliases.
# This helps the hot board path because the board items usually only mention
# the brand sub-line (e.g. "腾势") and not the parent group name.
KEYWORD_ALIASES: dict[str, list[str]] = {
    "新能源汽车": ["新能源汽车", "新能源车", "新能源", "电动车", "电动汽车", "电车", "混动", "插混", "增程", "动力电池", "电池", "禁售燃油车", "燃油车"],
    "新能源车": ["新能源车", "新能源汽车", "新能源", "电动车", "电动汽车"],
    "新能源": ["新能源", "新能源汽车", "新能源车"],
    "电动车": ["电动车", "电动汽车", "新能源车", "新能源汽车"],
    "电动汽车": ["电动汽车", "电动车", "新能源车", "新能源汽车"],
    "比亚迪": ["比亚迪", "腾势", "方程豹", "仰望", "弗迪", "byd"],
    "特斯拉": ["特斯拉", "Tesla", "Model Y", "Model 3"],
    "蔚来": ["蔚来", "NIO", "乐道", "萤火虫"],
    "理想": ["理想", "理想汽车", "Li Auto"],
    "小鹏": ["小鹏", "小鹏汽车", "XPENG"],
    "小米": ["小米", "小米汽车", "小米SU7", "YU7"],
    "华为": ["华为", "问界", "鸿蒙智行", "智界", "享界", "尊界", "尚界"],
    "充电桩": ["充电桩", "充电站", "充电", "换电", "超充", "快充"],
    "充电": ["充电", "充电桩", "充电站", "超充"],
    "换电": ["换电", "充电桩"],
    "汽车": ["汽车", "新车", "上市", "发布", "亮相", "禁售燃油车", "燃油车", "车企", "国产车"],
}

REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

OUTPUT_FILE = "demos/toutiao_heat_filter/output/demo_result.json"

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/html",
            "User-Agent": USER_AGENT,
            "Referer": "https://www.toutiao.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="replace")


def search_phrase(phrase: str) -> list[dict[str, Any]]:
    """Hit Toutiao search JSON endpoint for a phrase and parse the DOM."""
    params = urlencode(
        {
            "keyword": phrase,
            "pd": "information",
            "source": "search_subtab_switch",
            "from": "information",
            "format": "json",
            "count": "10",
            "offset": "0",
        }
    )
    text = fetch_text(f"{SEARCH_URL}?{params}")
    return parse_search(text, phrase)


def search_phrase_pages(
    phrase: str,
    max_pages: int = 3,
    per_page: int = 10,
    seen_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Paginated search for a single phrase. URL-deduped across pages and
    (optionally) article_id-deduped against a shared set."""
    seen: set[str] = set()
    if seen_ids is None:
        seen_ids = set()
    merged: list[dict[str, Any]] = []
    per_page = max(1, min(per_page, 50))
    for page in range(max_pages):
        offset = page * per_page
        params = urlencode(
            {
                "keyword": phrase,
                "pd": "information",
                "source": "search_subtab_switch",
                "from": "information",
                "format": "json",
                "count": str(per_page),
                "offset": str(offset),
            }
        )
        try:
            text = fetch_text(f"{SEARCH_URL}?{params}")
            batch = parse_search(text, phrase)
        except Exception as exc:
            print(f"    page {page} search failed: {exc}")
            break
        for item in batch:
            url = item.get("url", "")
            canonical = _canonical_url(url) if _is_content_url(url) else item.get("item_id", "")
            if canonical in seen:
                continue
            seen.add(canonical)
            aid = extract_article_id(url)
            if aid:
                if aid in seen_ids:
                    continue
                seen_ids.add(aid)
            merged.append(item)
    return merged


# ---------------------------------------------------------------------------
# LLM client (Anthropic-compatible HTTP API; tested with MiniMax)
# ---------------------------------------------------------------------------


LLM_CACHE_DIR = "demos/toutiao_heat_filter/output/llm_cache"
LLM_DEFAULT_BASE_URL = "https://api.minimaxi.com/anthropic"
LLM_DEFAULT_MODEL = "MiniMax-Text-01"


class LLMUnavailable(RuntimeError):
    """Raised when the LLM is not configured (no API key, etc.)."""


def _llm_env() -> dict[str, str]:
    """Read LLM config from env, preferring MINIMAX_* then falling back to ANTHROPIC_*."""
    api_key = (
        os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    base_url = (
        os.environ.get("MINIMAX_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL")
        or LLM_DEFAULT_BASE_URL
    ).rstrip("/")
    model = (
        os.environ.get("MINIMAX_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or LLM_DEFAULT_MODEL
    ).strip()
    return {"api_key": api_key, "base_url": base_url, "model": model}


def _llm_cache_path(cache_dir: str, prompt: str, system: str | None, model: str) -> str:
    payload = json.dumps({"model": model, "system": system or "", "prompt": prompt}, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return os.path.join(cache_dir, f"{digest}.json")


def call_llm(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    use_cache: bool = True,
    cache_dir: str = LLM_CACHE_DIR,
) -> str:
    """Call an Anthropic-format chat completion. Returns the assistant text.

    Reads MINIMAX_API_KEY / MINIMAX_BASE_URL / MINIMAX_MODEL from env.
    Caches responses under cache_dir keyed by sha256(model+system+prompt).
    Raises LLMUnavailable when the API key is missing.
    """
    env = _llm_env()
    if not env["api_key"]:
        raise LLMUnavailable("MINIMAX_API_KEY is not set in env")

    if use_cache:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = _llm_cache_path(cache_dir, prompt, system, env["model"])
        if os.path.exists(cache_path):
            try:
                cached = json.load(open(cache_path, encoding="utf-8"))
                return cached["text"]
            except (json.JSONDecodeError, KeyError, OSError):
                pass

    body = {
        "model": env["model"],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    url = f"{env['base_url']}/v1/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": env["api_key"],
            "anthropic-version": "2023-06-01",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise LLMUnavailable(f"LLM call failed: {exc}") from exc

    parts = payload.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    if not text:
        raise LLMUnavailable(f"LLM returned no text: {payload}")

    if use_cache:
        try:
            with open(cache_path, "w", encoding="utf-8") as fp:
                json.dump(
                    {"model": env["model"], "system": system or "", "prompt": prompt, "text": text},
                    fp,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError:
            pass
    return text


def _strip_code_fence(text: str) -> str:
    """Remove leading/trailing ```json ... ``` fences if present."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Article info (Stage 2)
# ---------------------------------------------------------------------------


def extract_article_id(url: str) -> str | None:
    match = re.search(r"/(?:article|trending|group)/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"(?:groupid|item_id)=(\d+)", url)
    return match.group(1) if match else None


def fetch_article_info(article_id: str) -> dict[str, Any] | None:
    """Hit the mobile article info endpoint. Returns the 'data' payload or None."""
    url = ARTICLE_INFO_URL_TEMPLATE.format(article_id=article_id)
    try:
        text = fetch_text(url)
        payload = json.loads(text)
    except Exception:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    return data


def compute_article_heat(metrics: dict[str, int]) -> int:
    """Weighted sum of impression / digg / comment / repost / repin counts."""
    total = 0
    for field, weight in ARTICLE_HEAT_WEIGHTS.items():
        total += int(metrics.get(field, 0)) * weight
    return total


def enrich_with_article_heat(item: dict[str, Any]) -> dict[str, Any]:
    """Fetch article info and attach article_heat metrics to the item.

    Does nothing if article id cannot be extracted or info fetch fails.
    """
    article_id = extract_article_id(item.get("url", ""))
    if not article_id:
        return item
    info = fetch_article_info(article_id)
    if info is None:
        item["article_info_status"] = "fetch_failed"
        return item
    raw_counts = {
        "impression_count": int(info.get("impression_count") or 0),
        "digg_count": int(info.get("digg_count") or 0),
        "comment_count": int(info.get("comment_count") or 0),
        "repost_count": int(info.get("repost_count") or 0),
        "repin_count": int(info.get("repin_count") or 0),
    }
    composite = compute_article_heat(raw_counts)
    item["article_heat"] = composite
    was_hot_board = item.get("source_kind") == "hot_board"
    if was_hot_board:
        item["metric_name"] = "hot_value+article_heat"
    else:
        item["hot_value"] = composite
        item["metric_name"] = "article_heat"
        item["source_kind"] = "article_info"
    item["raw_counts"] = raw_counts
    item["content_html"] = info.get("content") or ""
    item["article_info_status"] = "ok"
    item["article_title"] = info.get("title") or item.get("title", "")
    item["is_toutiao_hot"] = bool(info.get("is_toutiao_hot"))
    item["is_original"] = bool(info.get("is_original"))
    return item


# ---------------------------------------------------------------------------
# HTML -> plain text + file output
# ---------------------------------------------------------------------------


def html_to_text(html: str) -> str:
    """Lightweight HTML to text for article body content."""
    if not html:
        return ""
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?(p|br|h[1-6]|li|tr|div)\b[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = html_mod.unescape(cleaned)
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)


def slugify_for_filename(value: str, max_length: int = 50) -> str:
    """Safe ASCII-ish slug for filenames. Falls back to 'untitled' on empty."""
    value = value or ""
    value = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", value)
    value = re.sub(r"\s+", "_", value).strip("_")
    if not value:
        return "untitled"
    return value[:max_length]


def save_article_text(
    item: dict[str, Any],
    rank: int,
    output_dir: str,
    fetched_at: str,
) -> str | None:
    """Save a single article's body to TXT. Returns the file path or None."""
    body_html = item.get("content_html") or ""
    body_text = html_to_text(body_html)
    if not body_text:
        return None
    title = item.get("article_title") or item.get("title") or "untitled"
    slug = slugify_for_filename(title)
    filename = f"{rank:02d}_{slug}.txt"
    path = os.path.join(output_dir, filename)
    raw = item.get("raw_counts") or {}
    header_lines = [
        f"Title: {title}",
        f"URL: {item.get('url', '')}",
        f"Keyword: {item.get('matched_keyword', '')}",
        f"Fetched at: {fetched_at}",
        f"Article heat (composite): {item.get('hot_value', 0):,}",
        "Raw counts: "
        + ", ".join(f"{k}={raw.get(k, 0):,}" for k in
                    ("impression_count", "digg_count", "comment_count", "repost_count", "repin_count")),
        f"is_toutiao_hot: {item.get('is_toutiao_hot', False)}",
        f"is_original: {item.get('is_original', False)}",
        "",
        "=" * 60,
        "",
    ]
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(header_lines))
        fp.write(body_text)
        fp.write("\n")
    return path


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_hot_board(text: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    items: list[dict[str, Any]] = []
    for rank, row in enumerate(payload.get("data", []) or [], start=1):
        cluster_id = str(row.get("ClusterIdStr") or row.get("ClusterId") or "").strip()
        title = str(row.get("Title") or "").strip()
        url = str(row.get("Url") or "").strip()
        if not cluster_id or not title or not url:
            continue
        items.append(
            {
                "item_id": f"toutiao_{cluster_id}",
                "title": title,
                "url": url,
                "rank": rank,
                "hot_value": _int_or_none(row.get("HotValue")),
                "label": str(row.get("Label") or "").strip(),
                "category": _category(row),
                "query_word": str(row.get("QueryWord") or "").strip(),
                "source_kind": "hot_board",
            }
        )
    return items


class _ResultLinkParser(HTMLParser):
    """Lightweight parser that extracts <a href=...> blocks from search DOM."""

    def __init__(self) -> None:
        super().__init__()
        self._active_href: str = ""
        self._active_parts: list[str] = []
        self._text_buffer: list[str] = []
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href:
                self._flush()
                self._active_href = str(href)
                self._active_parts = []
                self._text_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_href:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._active_href:
            cleaned = re.sub(r"\s+", " ", data).strip()
            if cleaned:
                self._text_buffer.append(cleaned)
                if not self._active_parts:
                    self._active_parts.append(cleaned)

    def _flush(self) -> None:
        if self._active_href and self._active_parts:
            self.results.append(
                {
                    "href": self._active_href,
                    "title": " ".join(self._active_parts).strip(),
                    "text": "\n".join(self._text_buffer).strip(),
                }
            )
        self._active_href = ""
        self._active_parts = []
        self._text_buffer = []

    def close(self) -> None:
        self._flush()
        super().close()


def _resolve_jump_url(href: str) -> str:
    from urllib.parse import parse_qs

    absolute = href if href.startswith("http") else f"https://so.toutiao.com{href}"
    parsed = urlparse(absolute)
    if not parsed.path.startswith("/search/jump"):
        return absolute
    outer = parse_qs(parsed.query).get("url", [""])[0]
    if not outer:
        return absolute
    nested = parse_qs(urlparse(outer).query).get("h5_url", [""])[0]
    return nested or outer


def _is_content_url(url: str) -> bool:
    return (
        "/search/jump" in url
        or "toutiao.com/article/" in url
        or "toutiao.com/trending/" in url
        or "toutiao.com/group/" in url
    )


def _search_heat(text: str, total_count: int, rank: int) -> tuple[int | None, str]:
    hot_match = re.search(r"热度\s*([0-9.]+)\s*(万)?", text)
    if hot_match:
        value = float(hot_match.group(1))
        if hot_match.group(2) == "万":
            value *= 10_000
        return int(value), "search_heat"

    reads_match = re.search(r"阅读\s*([0-9.]+)\s*(万)?", text)
    comments_match = re.search(r"评论\s*([0-9.]+)\s*(万)?", text)
    if reads_match or comments_match:
        total = 0
        if reads_match:
            v = float(reads_match.group(1))
            if reads_match.group(2) == "万":
                v *= 10_000
            total += int(v)
        if comments_match:
            v = float(comments_match.group(1))
            if comments_match.group(2) == "万":
                v *= 10_000
            total += int(v)
        return total, "search_engagement"

    return max(total_count - rank + 1, 1), "search_rank"


def parse_search(text: str, phrase: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    dom = str(payload.get("dom") or "")
    total_count = _int_or_none(payload.get("count")) or 0
    parser = _ResultLinkParser()
    parser.feed(dom)
    parser.close()
    if total_count > 0 and not parser.results:
        return [
            {
                "item_id": f"toutiao_search_keyword_{_slug(phrase)}",
                "title": phrase,
                "url": f"{SEARCH_URL}?{urlencode({'keyword': phrase, 'pd': 'information'})}",
                "rank": 1,
                "hot_value": max(total_count, 1),
                "metric_name": "search_rank",
                "source_kind": "search_keyword_hit",
                "search_phrase": phrase,
            }
        ]
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    rank = 0
    for link in parser.results:
        href = link["href"]
        resolved = _resolve_jump_url(href)
        if not _is_content_url(resolved):
            continue
        canonical = _canonical_url(resolved)
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        rank += 1
        heat, metric = _search_heat(link["text"], total_count, rank)
        items.append(
            {
                "item_id": f"toutiao_search_{_slug(phrase)}_{rank}",
                "title": link["title"],
                "url": resolved,
                "rank": rank,
                "hot_value": heat,
                "metric_name": metric,
                "source_kind": "search_result",
                "search_phrase": phrase,
            }
        )
    return items


# ---------------------------------------------------------------------------
# Matching + merging
# ---------------------------------------------------------------------------


def match_profile(hot_board: list[dict[str, Any]], phrase: str) -> list[dict[str, Any]]:
    """Substring match against title / query_word. Case-insensitive."""
    needle = phrase.lower()
    matched: list[dict[str, Any]] = []
    for item in hot_board:
        title = item["title"].lower()
        query_word = item.get("query_word", "").lower()
        if needle in title or needle in query_word:
            matched.append(item)
    return matched


def merge_with_hot_board(
    search_items: list[dict[str, Any]],
    hot_board_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """URL-based merge: search items that overlap with hot board inherit HotValue."""
    by_url = {_canonical_url(item["url"]): item for item in hot_board_items}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in search_items:
        canonical = _canonical_url(s["url"]) if _is_content_url(s["url"]) else s["item_id"]
        if canonical in seen:
            continue
        hb = by_url.get(canonical)
        if hb is not None:
            merged.append(
                {
                    "item_id": hb["item_id"],
                    "title": hb["title"],
                    "url": hb["url"],
                    "rank": hb["rank"],
                    "hot_value": hb["hot_value"],
                    "metric_name": "hot_value",
                    "source_kind": "search_hot_board_overlap",
                    "search_phrase": s.get("search_phrase", ""),
                }
            )
        else:
            merged.append(s)
        seen.add(canonical)
    return merged


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def filter_by_hot_value(
    items: list[dict[str, Any]],
    threshold: int,
    metric_names: tuple[str, ...] = ("hot_value", "article_heat"),
) -> tuple[list[dict[str, Any]], int]:
    """Apply threshold to items whose metric_name is in metric_names.

    Items with other metrics (e.g. search_rank) are always kept.
    Returns (kept, dropped_count).
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        if item.get("metric_name") in metric_names:
            hv = item.get("hot_value") or 0
            if hv >= threshold:
                kept.append(item)
            else:
                dropped += 1
        else:
            kept.append(item)
    return kept, dropped


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_hot_value_distribution(values: list[int]) -> None:
    if not values:
        print("  (no values)")
        return
    sorted_vals = sorted(values, reverse=True)
    print(f"  count={len(sorted_vals)}")
    print(f"  max={sorted_vals[0]:>12,}  min={sorted_vals[-1]:>12,}")
    print(f"  median={sorted_vals[len(sorted_vals) // 2]:>12,}  mean={sum(sorted_vals) // len(sorted_vals):>12,}")
    print()
    buckets = [
        ("< 500K", 0, 500_000),
        ("500K - 1M", 500_000, 1_000_000),
        ("1M - 2M", 1_000_000, 2_000_000),
        ("2M - 5M", 2_000_000, 5_000_000),
        ("5M - 10M", 5_000_000, 10_000_000),
        (">= 10M", 10_000_000, float("inf")),
    ]
    print(f"  {'bucket':<14}{'count':<8}{'pct':<8}")
    for label, lo, hi in buckets:
        n = sum(1 for v in sorted_vals if lo <= v < hi)
        pct = n * 100 / len(sorted_vals)
        print(f"  {label:<14}{n:<8}{pct:>5.1f}%")
    print()


def print_section(title: str) -> None:
    print()
    print("=" * 78)
    print(f" {title}")
    print("=" * 78)


def print_table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> None:
    widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print("  " + fmt.format(*headers))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print("  " + fmt.format(*row))


# ---------------------------------------------------------------------------
# Focused mode: search keywords, enrich with article heat, return top N
# ---------------------------------------------------------------------------


def run_focused(keywords: list[str], top_n: int) -> None:
    fetched_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S%z")

    print_section(f"Focused mode: top {top_n} for keywords {keywords}")

    all_results: list[dict[str, Any]] = []
    start = time.time()
    for keyword in keywords:
        print(f"\n  searching '{keyword}' ...")
        try:
            items = search_phrase(keyword)
        except Exception as exc:
            print(f"    search failed: {exc}")
            continue
        print(f"    raw results: {len(items)}")

        enriched_count = 0
        for item in items:
            item["matched_keyword"] = keyword
            if not extract_article_id(item.get("url", "")):
                continue
            enrich_with_article_heat(item)
            if item.get("article_info_status") == "ok":
                enriched_count += 1
        print(f"    enriched with article info: {enriched_count}")
        all_results.extend(items)

    elapsed = time.time() - start
    print(f"\n  total fetches: {len(all_results)}  elapsed={elapsed:.1f}s")

    heat_items = [it for it in all_results if it.get("metric_name") == "article_heat"]
    heat_items.sort(key=lambda it: -(it.get("hot_value") or 0))
    top = heat_items[:top_n]

    print()
    print(f"  Heat-enriched results: {len(heat_items)}")
    print(f"  Showing top {len(top)} sorted by article_heat desc")
    print()

    if not top:
        print("  No heat-enriched results to show.")
        return

    print_table(
        ("rank", "heat", "impr", "digg", "cmt", "repost", "repin", "th_hot", "title"),
        [
            (
                i + 1,
                f"{it.get('hot_value', 0):,}",
                f"{it.get('raw_counts', {}).get('impression_count', 0):,}",
                f"{it.get('raw_counts', {}).get('digg_count', 0):,}",
                f"{it.get('raw_counts', {}).get('comment_count', 0):,}",
                f"{it.get('raw_counts', {}).get('repost_count', 0):,}",
                f"{it.get('raw_counts', {}).get('repin_count', 0):,}",
                "Y" if it.get("is_toutiao_hot") else "",
                (it.get("article_title") or it.get("title", ""))[:60],
            )
            for i, it in enumerate(top)
        ],
    )

    run_id = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    texts_dir = f"demos/toutiao_heat_filter/output/article_texts/{run_id}"
    os.makedirs(texts_dir, exist_ok=True)
    saved_paths: list[str] = []
    skipped_no_body = 0
    for i, item in enumerate(top, start=1):
        path = save_article_text(item, rank=i, output_dir=texts_dir, fetched_at=fetched_at)
        if path is None:
            skipped_no_body += 1
        else:
            saved_paths.append(path)

    print()
    print(f"  Saved {len(saved_paths)} article text file(s) to:")
    print(f"    {texts_dir}")
    if skipped_no_body:
        print(f"  Skipped {skipped_no_body} item(s) with no body content")
    for path in saved_paths[:5]:
        size = os.path.getsize(path)
        print(f"    {os.path.basename(path):<60} {size:>7,} bytes")
    if len(saved_paths) > 5:
        print(f"    ... and {len(saved_paths) - 5} more")

    out_file = f"demos/toutiao_heat_filter/output/focused_{int(time.time())}.json"
    payload = {
        "fetched_at": fetched_at,
        "keywords": keywords,
        "top_n": top_n,
        "weights": ARTICLE_HEAT_WEIGHTS,
        "results": [
            {
                "rank": i + 1,
                "title": it.get("article_title") or it.get("title"),
                "url": it.get("url"),
                "matched_keyword": it.get("matched_keyword"),
                "article_heat": it.get("hot_value"),
                "raw_counts": it.get("raw_counts"),
                "is_toutiao_hot": it.get("is_toutiao_hot"),
                "is_original": it.get("is_original"),
            }
            for i, it in enumerate(top)
        ],
    }
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    print()
    print(f"Wrote {out_file}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _category(row: dict[str, Any]) -> str:
    cats = row.get("InterestCategory")
    if isinstance(cats, list) and cats:
        return str(cats[0]).strip()
    return str(row.get("Label") or "").strip()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _canonical_url(url: str) -> str:
    return url.split("?", maxsplit=1)[0].rstrip("/")


def _slug(value: str) -> str:
    return re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_").lower() or "keyword"


def run() -> None:
    fetched_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S%z")

    print_section("Step 1 - Fetch hot board")
    hot_board_raw = fetch_text(HOT_BOARD_URL)
    hot_board = parse_hot_board(hot_board_raw)
    print(f"  fetched {len(hot_board)} hot board items at {fetched_at}")

    print_section("Step 2 - HotValue distribution (all 50 hot board items)")
    hv_values = [item["hot_value"] for item in hot_board if item["hot_value"] is not None]
    print_hot_value_distribution(hv_values)

    print_section("Step 3 - Match profile queries against hot board")
    profile_matches: list[dict[str, Any]] = []
    for query_id, phrase, alias in PROFILE_QUERIES:
        hits = match_profile(hot_board, phrase)
        print(f"  {query_id} '{phrase}'  ->  {len(hits)} hot board hit(s)")
        for h in hits:
            profile_matches.append({**h, "matched_query_id": query_id, "matched_phrase": phrase})
    print(f"\n  total profile-relevant hot board items: {len(profile_matches)}")
    if profile_matches:
        print_table(
            ("rank", "hot_value", "title"),
            [(m["rank"], f"{m['hot_value']:,}", m["title"][:48]) for m in profile_matches],
        )

    print_section("Step 4 - Search API for each phrase")
    search_by_phrase: dict[str, list[dict[str, Any]]] = {}
    for query_id, phrase, alias in PROFILE_QUERIES:
        try:
            items = search_phrase(phrase)
        except Exception as exc:
            print(f"  {query_id} '{phrase}'  ->  search failed: {exc}")
            continue
        search_by_phrase[phrase] = items
        kinds: dict[str, int] = {}
        for it in items:
            kinds[it["source_kind"]] = kinds.get(it["source_kind"], 0) + 1
        print(f"  {query_id} '{phrase}'  ->  {len(items)} item(s)  kinds={kinds}")

    print_section("Step 5 - Merge search + hot board per phrase")
    all_merged: list[dict[str, Any]] = []
    for query_id, phrase, alias in PROFILE_QUERIES:
        search_items = search_by_phrase.get(phrase, [])
        phrase_hot_board = [m for m in profile_matches if m["matched_phrase"] == phrase]
        merged = merge_with_hot_board(search_items, phrase_hot_board)
        for item in merged:
            item["matched_query_id"] = query_id
            item["matched_phrase"] = phrase
            item["alias_for"] = alias
        all_merged.extend(merged)
        kinds: dict[str, int] = {}
        for it in merged:
            kinds[it["source_kind"]] = kinds.get(it["source_kind"], 0) + 1
        print(f"  {query_id} '{phrase}'  ->  merged={len(merged)}  kinds={kinds}")

    print_section("Step 6 - Threshold sweep")
    print(f"  {'threshold':<14}{'kept':<8}{'dropped':<10}{'kept(hot_value only)':<24}")
    sweep_results: list[dict[str, Any]] = []
    for threshold in HOT_VALUE_THRESHOLDS:
        kept, dropped = filter_by_hot_value(all_merged, threshold)
        hot_value_kept = sum(1 for it in kept if it.get("metric_name") == "hot_value")
        sweep_results.append(
            {"threshold": threshold, "kept": len(kept), "dropped": dropped, "hot_value_kept": hot_value_kept}
        )
        print(f"  {threshold:<14,}{len(kept):<8}{dropped:<10}{hot_value_kept:<24}")

    print_section("Step 7 - Survivors at threshold=1,000,000")
    sample_threshold = 1_000_000
    kept, dropped = filter_by_hot_value(all_merged, sample_threshold)
    print(f"  kept={len(kept)}  dropped={dropped}")
    if kept:
        kept_sorted = sorted(
            kept,
            key=lambda it: (
                -(it.get("hot_value") or 0) if it.get("metric_name") == "hot_value" else 1,
                it.get("rank") or 9999,
            ),
        )
        print_table(
            ("rank", "hot_value", "metric", "source", "title"),
            [
                (
                    it.get("rank"),
                    f"{(it.get('hot_value') or 0):,}",
                    it.get("metric_name", ""),
                    it.get("source_kind", ""),
                    it.get("title", "")[:44],
                )
                for it in kept_sorted
            ],
        )

    print_section("Step 8 - Survivors at threshold=5,000,000")
    sample_threshold = 5_000_000
    kept, dropped = filter_by_hot_value(all_merged, sample_threshold)
    print(f"  kept={len(kept)}  dropped={dropped}")
    if kept:
        kept_sorted = sorted(
            kept,
            key=lambda it: (
                -(it.get("hot_value") or 0) if it.get("metric_name") == "hot_value" else 1,
                it.get("rank") or 9999,
            ),
        )
        print_table(
            ("rank", "hot_value", "metric", "source", "title"),
            [
                (
                    it.get("rank"),
                    f"{(it.get('hot_value') or 0):,}",
                    it.get("metric_name", ""),
                    it.get("source_kind", ""),
                    it.get("title", "")[:44],
                )
                for it in kept_sorted
            ],
        )

    print_section("Step 9 - Stage 2: enrich search items with article info heat")
    enrichable = [it for it in all_merged if extract_article_id(it.get("url", ""))]
    print(f"  enrichable items: {len(enrichable)} (have article id in url)")
    enriched_results: list[dict[str, Any]] = []
    start = time.time()
    for index, item in enumerate(enrichable, start=1):
        enriched = enrich_with_article_heat(item)
        enriched_results.append(enriched)
        if index % 10 == 0 or index == len(enrichable):
            ok = sum(1 for it in enriched_results if it.get("article_info_status") == "ok")
            print(f"    [{index}/{len(enrichable)}] ok={ok}  elapsed={time.time() - start:.1f}s")
    elapsed = time.time() - start
    print(f"  done in {elapsed:.1f}s, avg {elapsed / max(len(enrichable), 1):.2f}s/article")

    print_section("Step 10 - Article heat distribution (enriched items)")
    ok_items = [it for it in enriched_results if it.get("article_info_status") == "ok"]
    fail_items = [it for it in enriched_results if it.get("article_info_status") != "ok"]
    print(f"  fetched_ok={len(ok_items)}  failed={len(fail_items)}")
    heat_values = [it["hot_value"] for it in ok_items if isinstance(it.get("hot_value"), int)]
    if heat_values:
        print_hot_value_distribution(heat_values)
    print(f"  is_toutiao_hot flag: {sum(1 for it in ok_items if it.get('is_toutiao_hot'))}")
    print(f"  is_original   flag: {sum(1 for it in ok_items if it.get('is_original'))}")

    if heat_values:
        print("  raw engagement metrics (median):")
        for field in ("impression_count", "digg_count", "comment_count", "repost_count", "repin_count"):
            vals = sorted((it.get("raw_counts", {}).get(field, 0) for it in ok_items), reverse=True)
            if vals:
                print(f"    {field:<18} max={vals[0]:>8,}  median={vals[len(vals)//2]:>6,}  mean={sum(vals)//len(vals):>6,}")

    print_section("Step 11 - Article-heat threshold sweep")
    print(f"  {'threshold':<14}{'kept':<8}{'dropped':<10}{'kept(article_heat)':<24}")
    article_sweep: list[dict[str, Any]] = []
    for threshold in ARTICLE_HEAT_THRESHOLDS:
        kept, dropped = filter_by_hot_value(enriched_results, threshold, metric_names=("article_heat",))
        art_kept = sum(1 for it in kept if it.get("metric_name") == "article_heat")
        article_sweep.append({"threshold": threshold, "kept": len(kept), "dropped": dropped, "article_heat_kept": art_kept})
        print(f"  {threshold:<14,}{len(kept):<8}{dropped:<10}{art_kept:<24}")

    print_section("Step 12 - Survivors at article_heat >= 200")
    sample_threshold = 200
    kept, dropped = filter_by_hot_value(enriched_results, sample_threshold, metric_names=("article_heat",))
    print(f"  kept={len(kept)}  dropped={dropped}")
    if kept:
        kept_sorted = sorted(
            [it for it in kept if it.get("metric_name") == "article_heat"],
            key=lambda it: -(it.get("hot_value") or 0),
        )
        print_table(
            ("heat", "impr", "digg", "cmt", "repost", "repin", "title"),
            [
                (
                    f"{(it.get('hot_value') or 0):,}",
                    f"{it.get('raw_counts', {}).get('impression_count', 0):,}",
                    f"{it.get('raw_counts', {}).get('digg_count', 0):,}",
                    f"{it.get('raw_counts', {}).get('comment_count', 0):,}",
                    f"{it.get('raw_counts', {}).get('repost_count', 0):,}",
                    f"{it.get('raw_counts', {}).get('repin_count', 0):,}",
                    (it.get("article_title") or it.get("title", ""))[:50],
                )
                for it in kept_sorted
            ],
        )

    # Persist for offline inspection.
    output_payload = {
        "fetched_at": fetched_at,
        "profile_queries": [
            {"query_id": q[0], "phrase": q[1], "alias_for": q[2]} for q in PROFILE_QUERIES
        ],
        "hot_board_count": len(hot_board),
        "hot_value_distribution": {
            "max": max(hv_values) if hv_values else None,
            "min": min(hv_values) if hv_values else None,
            "median": sorted(hv_values)[len(hv_values) // 2] if hv_values else None,
            "mean": (sum(hv_values) // len(hv_values)) if hv_values else None,
        },
        "profile_matches": profile_matches,
        "search_by_phrase": search_by_phrase,
        "merged": all_merged,
        "threshold_sweep": sweep_results,
        "article_heat": {
            "enriched": enriched_results,
            "ok_count": len(ok_items),
            "fail_count": len(fail_items),
            "distribution": {
                "max": max(heat_values) if heat_values else None,
                "min": min(heat_values) if heat_values else None,
                "median": sorted(heat_values)[len(heat_values) // 2] if heat_values else None,
                "mean": (sum(heat_values) // len(heat_values)) if heat_values else None,
            },
            "article_heat_threshold_sweep": article_sweep,
            "weights": ARTICLE_HEAT_WEIGHTS,
        },
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fp:
        json.dump(output_payload, fp, ensure_ascii=False, indent=2)
    print()
    print(f"Wrote {OUTPUT_FILE}")


# ---------------------------------------------------------------------------
# Hybrid mode: hot board + multi-page keyword search
# ---------------------------------------------------------------------------


def _contains_any(haystack: str, needles: list[str]) -> str | None:
    """Return the first needle that appears in haystack (case-insensitive)."""
    if not haystack:
        return None
    h = haystack.lower()
    for n in needles:
        if n and n.lower() in h:
            return n
    return None


def expand_keywords(
    keywords: list[str],
    *,
    use_llm: bool = False,
    system: str | None = None,
) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """Expand user keywords with KEYWORD_ALIASES (and optionally LLM).

    Returns:
        expanded: deduplicated list of all aliases (preserves order, original keyword first)
        alias_map: original_keyword -> list of aliases used (including itself)
        source_map: alias -> "static" | "llm" (provenance per alias, for debugging)
    """
    expanded: list[str] = []
    alias_map: dict[str, list[str]] = {}
    source_map: dict[str, str] = {}
    for kw in keywords:
        aliases = KEYWORD_ALIASES.get(kw) or [kw]
        alias_map[kw] = list(aliases)
        for a in aliases:
            if a and a not in expanded:
                expanded.append(a)
                source_map[a] = "static"
    if not expanded:
        expanded = list(keywords)

    if use_llm:
        llm_map = _llm_generate_aliases(keywords, system=system)
        for kw, aliases in llm_map.items():
            existing = alias_map.setdefault(kw, [kw])
            for a in aliases:
                if not a:
                    continue
                if a not in expanded:
                    expanded.append(a)
                    source_map[a] = "llm"
                if a not in existing:
                    existing.append(a)
    return expanded, alias_map, source_map


def _llm_generate_aliases(
    keywords: list[str],
    *,
    system: str | None = None,
) -> dict[str, list[str]]:
    """Ask the LLM for a {keyword: [aliases]} dict. Returns {} on failure."""
    if not keywords:
        return {}
    sys_prompt = system or (
        "你是一个中文互联网内容分析师。用户会给你一组兴趣关键词，"
        "请为每个关键词生成 5-12 个会出现在新闻标题、热搜榜、"
        "或微头条里的相关词（alias）。要求：\n"
        "1) alias 必须是中文媒体真实使用过的词；\n"
        "2) 包含品牌子系列、车系型号、概念词、相关实体；\n"
        "3) 排除明星姓名、敏感话题、跨领域歧义词；\n"
        "4) 直接输出 JSON 对象，key 是用户原词，value 是 alias 数组；"
        "不要 markdown 代码块标记，不要任何解释。"
    )
    user_prompt = (
        "用户关键词：" + json.dumps(keywords, ensure_ascii=False) + "\n"
        "请输出 JSON。"
    )
    try:
        raw = call_llm(user_prompt, system=sys_prompt, max_tokens=2048, temperature=0.2)
    except LLMUnavailable as exc:
        print(f"    LLM alias unavailable: {exc}")
        return {}
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"    LLM returned non-JSON: {exc}; first 200 chars: {raw[:200]!r}")
        return {}
    if not isinstance(data, dict):
        print("    LLM alias response is not a dict; ignoring")
        return {}
    out: dict[str, list[str]] = {}
    for kw in keywords:
        v = data.get(kw)
        if isinstance(v, list):
            out[kw] = [str(a).strip() for a in v if str(a).strip()]
    return out


def _match_hot_board(
    hot_board: list[dict[str, Any]],
    keywords: list[str],
    *,
    use_llm: bool = False,
) -> list[dict[str, Any]]:
    """Return hot board items that contain any (expanded) keyword in
    title / query_word / label / category.
    """
    expanded, alias_map, _ = expand_keywords(keywords, use_llm=use_llm)
    matched: list[dict[str, Any]] = []
    for item in hot_board:
        title = item.get("title", "")
        query_word = item.get("query_word", "")
        label = item.get("label", "")
        category = item.get("category", "")
        haystacks = (title, query_word, label, category)
        hit = next(
            (
                kw
                for kw in expanded
                if any(_contains_any(field, [kw]) for field in haystacks)
            ),
            None,
        )
        if hit:
            user_kw = next(
                (uk for uk, aliases in alias_map.items() if hit in aliases),
                hit,
            )
            matched.append(
                {
                    **item,
                    "matched_keyword": user_kw,
                    "matched_alias": hit,
                    "source_kind": "hot_board",
                }
            )
    return matched


def _enrich_parallel(
    items: list[dict[str, Any]],
    max_workers: int = 8,
) -> None:
    """Fetch article info in parallel; mutate items in place."""
    eligible = [it for it in items if extract_article_id(it.get("url", ""))]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(enrich_with_article_heat, it): it for it in eligible}
        for fut in as_completed(futures):
            fut.result()


def _hybrid_score(item: dict[str, Any]) -> tuple[float, float, float, int]:
    """Unified log-scale score so HotValue (1.5K-21M) and article_heat (0-50K) are comparable.

    Returns (score, is_hb_boost, is_th_hot_boost, hot_board_rank) for sorting.

    The score is the larger of:
      - log10(hot_value + 1)        for hot board items
      - log10((article_heat + 1) * 1000)  for search items (scaled up)
    Boosted by +0.5 if hot board, +0.3 if is_toutiao_hot=True.
    """
    is_hb = item.get("source_kind") in ("hot_board", "hot_board+search")
    hot_value = int(item.get("hot_value") or 0)
    article_heat = int(item.get("article_heat") or 0)
    if is_hb:
        primary = math.log10(max(hot_value, 0) + 1)
    else:
        primary = math.log10(max(article_heat, 0) + 1)
        primary += 3  # scale search heat up so it competes with hot board
    boost = 0.0
    if is_hb:
        boost += 0.5
    if item.get("is_toutiao_hot"):
        boost += 0.3
    hot_board_rank = int(item.get("hot_board_rank") or 9999)
    return (primary + boost, primary, float(boost), -hot_board_rank)


def run_hybrid(
    keywords: list[str],
    top_n: int,
    *,
    hot_board_min: int = 100_000,
    article_heat_min: int = 500,
    include_toutiao_hot: bool = True,
    search_pages: int = 3,
    per_page: int = 10,
    min_outputs: int | None = None,
    use_llm_alias: bool = False,
    use_llm_summary: bool = False,
    no_llm_cache: bool = False,
    output_dir: str = "demos/toutiao_heat_filter/output",
) -> None:
    """Hybrid mode: hot board matches + multi-page keyword search, dedupe by URL."""
    fetched_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S%z")
    min_outputs = min_outputs if min_outputs is not None else top_n

    print_section(
        f"Hybrid mode: hot board (HotValue>={hot_board_min:,}) + search "
        f"({search_pages} pages × {per_page}, article_heat>={article_heat_min:,}"
        f"{' or is_toutiao_hot' if include_toutiao_hot else ''})"
    )
    print(f"  keywords: {keywords}")

    # --- Step 1: hot board fetch + keyword filter (with alias expansion) ---
    t0 = time.time()
    hot_board_text = fetch_text(HOT_BOARD_URL)
    hot_board = parse_hot_board(hot_board_text)
    hb_matches = _match_hot_board(hot_board, keywords, use_llm=use_llm_alias)
    expanded, _, _ = expand_keywords(keywords, use_llm=use_llm_alias)
    print(f"\n  hot board: {len(hot_board)} items, {len(hb_matches)} keyword match(es) (expanded: {len(expanded)} terms)")
    if hb_matches:
        for hb in hb_matches[:5]:
            alias_note = f"  [via alias '{hb.get('matched_alias', hb.get('matched_keyword', ''))}']" if hb.get("matched_alias") and hb.get("matched_alias") != hb.get("matched_keyword") else ""
            print(f"    rank={hb['rank']:>2}  HotValue={hb['hot_value']:>10,}  matched={hb.get('matched_keyword','')}  {hb['title'][:38]}{alias_note}")
        if len(hb_matches) > 5:
            print(f"    ... and {len(hb_matches) - 5} more")

    # --- Step 2: multi-page keyword search (shared article_id dedup) ---
    print(f"\n  search: {len(keywords)} keyword(s) × {search_pages} pages")
    search_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for kw in keywords:
        print(f"    '{kw}' ...", end="", flush=True)
        batch = search_phrase_pages(
            kw, max_pages=search_pages, per_page=per_page, seen_ids=seen_ids
        )
        for x in batch:
            x["matched_keyword"] = kw
        search_items.extend(batch)
        print(f" raw={len(batch)}")
    print(f"  total search candidates: {len(search_items)} (unique article_ids: {len(seen_ids)})")

    # --- Step 3: enrich all enrichable candidates in parallel ---
    enrich_targets = [it for it in search_items if extract_article_id(it.get("url", ""))]
    enrich_targets.extend(hb for hb in hb_matches if extract_article_id(hb.get("url", "")))
    print(f"\n  enriching {len(enrich_targets)} candidate(s) with article info ...")
    _enrich_parallel(enrich_targets)
    ok = sum(1 for it in enrich_targets if it.get("article_info_status") == "ok")
    print(f"    enrichment ok: {ok}/{len(enrich_targets)}")

    # --- Step 4: filter search items by article_heat OR is_toutiao_hot ---
    kept_search: list[dict[str, Any]] = []
    for it in search_items:
        status = it.get("article_info_status")
        article_heat = int(it.get("article_heat") or 0)
        keep = False
        if status == "ok":
            if article_heat >= article_heat_min:
                keep = True
            elif include_toutiao_hot and it.get("is_toutiao_hot"):
                keep = True
        if keep:
            kept_search.append(it)
    print(f"  search items kept (heat>={article_heat_min}"
          f"{' or is_toutiao_hot' if include_toutiao_hot else ''}): {len(kept_search)}")

    # --- Step 5: merge by URL, prefer hot board version ---
    by_url: dict[str, dict[str, Any]] = {}
    for it in kept_search:
        if _is_content_url(it.get("url", "")):
            by_url[_canonical_url(it["url"])] = it
    merged: list[dict[str, Any]] = []
    for hb in hb_matches:
        url = hb.get("url", "")
        canonical = _canonical_url(url) if _is_content_url(url) else url
        existing = by_url.get(canonical)
        if existing is not None:
            existing["hot_value"] = hb["hot_value"]
            existing["source_kind"] = "hot_board+search"
            existing["hot_board_rank"] = hb["rank"]
            existing["hot_board_label"] = hb.get("label", "")
            existing["matched_alias"] = hb.get("matched_alias", existing.get("matched_keyword", ""))
            existing["metric_name"] = "hot_value+article_heat"
            merged.append(existing)
            by_url.pop(canonical, None)
        else:
            merged.append(hb)
    merged.extend(by_url.values())

    # --- Step 5b: secondary dedup by article_id (catches query-string variants) ---
    deduped: list[dict[str, Any]] = []
    seen_aids: dict[str, dict[str, Any]] = {}
    for it in merged:
        aid = extract_article_id(it.get("url", ""))
        if not aid:
            deduped.append(it)
            continue
        if aid in seen_aids:
            existing = seen_aids[aid]
            # Keep the one with higher hot_value (or article_heat if hot_value tied)
            score_new = int(it.get("hot_value") or 0) + int(it.get("article_heat") or 0) / 1000
            score_old = int(existing.get("hot_value") or 0) + int(existing.get("article_heat") or 0) / 1000
            if score_new > score_old:
                seen_aids[aid] = it
                idx = deduped.index(existing)
                deduped[idx] = it
        else:
            seen_aids[aid] = it
            deduped.append(it)
    dropped = len(merged) - len(deduped)
    if dropped:
        print(f"  article_id dedup: {len(merged)} -> {len(deduped)} ({dropped} duplicate(s) removed)")
    merged = deduped

    # --- Step 6: enforce hot_board_min on hot_board items ---
    before = len(merged)
    merged = [
        it for it in merged
        if not (it.get("source_kind") in ("hot_board", "hot_board+search") and (it.get("hot_value") or 0) < hot_board_min)
    ]
    print(f"  hot board filter (HotValue>={hot_board_min:,}): {before} -> {len(merged)}")

    # --- Step 7: unified log-based sort ---
    merged.sort(key=lambda it: _hybrid_score(it), reverse=True)

    # --- Step 8: keep enough results to satisfy min_outputs, then top N ---
    while len(merged) < min_outputs and search_pages < 8:
        search_pages += 1
        print(f"\n  need at least {min_outputs} results; extending search to {search_pages} pages")
        more_items: list[dict[str, Any]] = []
        for kw in keywords:
            batch = search_phrase_pages(
                kw, max_pages=search_pages, per_page=per_page, seen_ids=seen_ids
            )
            for x in batch:
                x["matched_keyword"] = kw
            more_items.extend(batch)
        new_only = []
        seen_urls = {
            _canonical_url(it["url"])
            for it in merged
            if _is_content_url(it.get("url", ""))
        }
        for it in more_items:
            url = it.get("url", "")
            c = _canonical_url(url) if _is_content_url(url) else it.get("item_id", "")
            if c in seen_urls:
                continue
            seen_urls.add(c)
            new_only.append(it)
        if not new_only:
            break
        _enrich_parallel([it for it in new_only if extract_article_id(it.get("url", ""))])
        new_kept = []
        for it in new_only:
            status = it.get("article_info_status")
            article_heat = int(it.get("article_heat") or 0)
            if status == "ok" and (
                article_heat >= article_heat_min
                or (include_toutiao_hot and it.get("is_toutiao_hot"))
            ):
                new_kept.append(it)
        for it in new_kept:
            if it not in merged:
                merged.append(it)
        merged.sort(key=lambda it: _hybrid_score(it), reverse=True)
        if len(merged) >= min_outputs:
            break

    top = merged[:top_n]
    elapsed = time.time() - t0
    print(f"\n  total candidates after merge+filter: {len(merged)}  top_n={top_n}  elapsed={elapsed:.1f}s")

    if not top:
        print("  No candidates survived the hybrid filter.")
        return

    print()
    headers = ("#", "src", "hot_value", "article_heat", "th_hot", "matched", "title")
    rows = []
    for i, it in enumerate(top, 1):
        is_hb = it.get("source_kind") in ("hot_board", "hot_board+search")
        rows.append(
            (
                i,
                it.get("source_kind", ""),
                f"{(it.get('hot_value') or 0):,}",
                f"{int(it.get('article_heat') or 0):,}",
                "Y" if it.get("is_toutiao_hot") else "",
                it.get("matched_keyword", "") or it.get("query_word", ""),
                (it.get("article_title") or it.get("title", ""))[:48],
            )
        )
    print_table(headers, rows)

    # --- Step 9: write TXT bodies ---
    run_id = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    texts_dir = f"{output_dir}/article_texts/{run_id}"
    os.makedirs(texts_dir, exist_ok=True)
    saved_paths: list[str] = []
    skipped_no_body = 0
    for i, item in enumerate(top, start=1):
        path = save_article_text(item, rank=i, output_dir=texts_dir, fetched_at=fetched_at)
        if path is None:
            skipped_no_body += 1
        else:
            saved_paths.append(path)

    print()
    print(f"  Saved {len(saved_paths)} article text file(s) to:")
    print(f"    {texts_dir}")
    if skipped_no_body:
        print(f"  Skipped {skipped_no_body} item(s) with no body content")
    for path in saved_paths[:5]:
        size = os.path.getsize(path)
        print(f"    {os.path.basename(path):<60} {size:>7,} bytes")
    if len(saved_paths) > 5:
        print(f"    ... and {len(saved_paths) - 5} more")

    # --- Step 10: LLM summary ---
    summary_path: str | None = None
    summary_text: str | None = None
    if use_llm_summary and top:
        summary_text, summary_path = _llm_summarize_results(
            keywords=keywords,
            top=top,
            fetched_at=fetched_at,
            texts_dir=texts_dir,
            no_cache=no_llm_cache,
        )

    out_file = f"{output_dir}/hybrid_{int(time.time())}.json"
    payload = {
        "fetched_at": fetched_at,
        "mode": "hybrid",
        "keywords": keywords,
        "top_n": top_n,
        "thresholds": {
            "hot_board_min": hot_board_min,
            "article_heat_min": article_heat_min,
            "include_toutiao_hot": include_toutiao_hot,
            "search_pages": search_pages,
            "per_page": per_page,
        },
        "weights": ARTICLE_HEAT_WEIGHTS,
        "results": [
            {
                "rank": i + 1,
                "title": it.get("article_title") or it.get("title"),
                "url": it.get("url"),
                "source_kind": it.get("source_kind"),
                "matched_keyword": it.get("matched_keyword") or it.get("query_word"),
                "hot_value": it.get("hot_value"),
                "metric_name": it.get("metric_name"),
                "article_heat": it.get("article_heat"),
                "raw_counts": it.get("raw_counts"),
                "is_toutiao_hot": it.get("is_toutiao_hot"),
                "is_original": it.get("is_original"),
                "hot_board_rank": it.get("hot_board_rank"),
            }
            for i, it in enumerate(top)
        ],
    }
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    if summary_path:
        payload["summary_path"] = summary_path
        with open(out_file, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
    print()
    print(f"Wrote {out_file}")
    if summary_path and summary_text:
        print()
        print("=" * 78)
        print("LLM summary:")
        print("=" * 78)
        print(summary_text)
        print("=" * 78)
        print(f"Summary file: {summary_path}")


# ---------------------------------------------------------------------------
# LLM summary
# ---------------------------------------------------------------------------


def _truncate_body_for_prompt(html_or_text: str, max_chars: int = 400) -> str:
    """Pull the first `max_chars` chars of a body, stripping extra whitespace."""
    if not html_or_text:
        return ""
    text = re.sub(r"\s+", " ", html_or_text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def _llm_summarize_results(
    *,
    keywords: list[str],
    top: list[dict[str, Any]],
    fetched_at: str,
    texts_dir: str,
    no_cache: bool,
) -> tuple[str | None, str | None]:
    """Ask the LLM to produce a Markdown summary of the top results.

    Returns (summary_text, summary_file_path) or (None, None) on failure.
    """
    system = (
        "你是一个中文内容趋势分析师。下面是用户用关键词抓到的热点文章列表，"
        "每条带有：标题、来源（hot_board 热榜/ search 搜索）、热度指标、"
        "以及正文前 400 字摘录。\n\n"
        "请输出 Markdown 总结，包括三个段落：\n"
        "1. **主题趋势**：3-5 个 bullet，归纳这些文章共同的话题方向；\n"
        "2. **重点文章**：挑出 2-3 条最值得读的，简要说明亮点；\n"
        "3. **延伸关键词**：建议 1-2 个用户可以继续追的衍生关键词。\n\n"
        "风格简洁、信息密度高，避免空话。"
    )
    items_payload: list[dict[str, Any]] = []
    for i, it in enumerate(top, 1):
        items_payload.append(
            {
                "rank": i,
                "title": it.get("article_title") or it.get("title"),
                "source": it.get("source_kind"),
                "matched_keyword": it.get("matched_keyword") or it.get("query_word"),
                "hot_value": int(it.get("hot_value") or 0),
                "article_heat": int(it.get("article_heat") or 0),
                "is_toutiao_hot": bool(it.get("is_toutiao_hot")),
                "body_excerpt": _truncate_body_for_prompt(it.get("content_html", ""), 400),
            }
        )
    user_prompt = (
        f"用户关键词：{json.dumps(keywords, ensure_ascii=False)}\n"
        f"抓取时间：{fetched_at}\n"
        f"结果数：{len(items_payload)}\n"
        "结果 JSON：\n" + json.dumps(items_payload, ensure_ascii=False, indent=2)
    )
    try:
        text = call_llm(
            user_prompt,
            system=system,
            max_tokens=2048,
            temperature=0.4,
            use_cache=not no_cache,
        )
    except LLMUnavailable as exc:
        print(f"  LLM summary unavailable: {exc}")
        return None, None

    summary_path = os.path.join(texts_dir, "summary.md")
    try:
        with open(summary_path, "w", encoding="utf-8") as fp:
            fp.write("# 关键词热点总结\n\n")
            fp.write(f"- 关键词：{', '.join(keywords)}\n")
            fp.write(f"- 抓取时间：{fetched_at}\n")
            fp.write(f"- 结果数：{len(items_payload)}\n\n")
            fp.write(text.strip() + "\n")
    except OSError as exc:
        print(f"  failed to write summary file: {exc}")
        summary_path = None
    return text.strip(), summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Toutiao hot article fetcher (standalone demo, no main package imports)."
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=["新能源汽车"],
        help="one or more search keywords (default: 新能源汽车)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="number of top heat-enriched results to return (default: 10)",
    )
    parser.add_argument(
        "--mode",
        choices=("hybrid", "focused", "explore"),
        default="hybrid",
        help=(
            "hybrid: hot board matches + multi-page keyword search (default); "
            "focused: single-page keyword search only; "
            "explore: full 12-step analysis"
        ),
    )
    parser.add_argument(
        "--search-pages",
        type=int,
        default=3,
        help="pages of search results to fetch per keyword in hybrid mode (default: 3)",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=10,
        help="results per search page (default: 10)",
    )
    parser.add_argument(
        "--hot-board-min",
        type=int,
        default=100_000,
        help="minimum HotValue to keep hot board matches in hybrid mode (default: 100,000)",
    )
    parser.add_argument(
        "--article-heat-min",
        type=int,
        default=500,
        help="minimum article_heat to keep search items in hybrid mode (default: 500)",
    )
    parser.add_argument(
        "--no-toutiao-hot",
        action="store_true",
        help="do not include search items just because is_toutiao_hot=True",
    )
    parser.add_argument(
        "--min-outputs",
        type=int,
        default=0,
        help="if fewer than N results survive, automatically extend search pages (0 = disabled)",
    )
    parser.add_argument(
        "--llm-alias",
        action="store_true",
        help="use LLM (env: MINIMAX_API_KEY) to expand keyword aliases for hot-board matching",
    )
    parser.add_argument(
        "--llm-summary",
        action="store_true",
        help="use LLM to write a Markdown summary of the top results",
    )
    parser.add_argument(
        "--no-llm-cache",
        action="store_true",
        help="do not read/write LLM response cache",
    )
    parser.add_argument(
        "--llm-cache-dir",
        default=LLM_CACHE_DIR,
        help=f"LLM response cache directory (default: {LLM_CACHE_DIR})",
    )
    parser.add_argument(
        "--explore",
        action="store_true",
        help="also run the multi-profile exploratory analysis (Steps 1-12)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.mode == "hybrid":
        run_hybrid(
            args.keywords,
            args.top,
            hot_board_min=args.hot_board_min,
            article_heat_min=args.article_heat_min,
            include_toutiao_hot=not args.no_toutiao_hot,
            search_pages=args.search_pages,
            per_page=args.per_page,
            min_outputs=args.min_outputs or None,
            use_llm_alias=args.llm_alias,
            use_llm_summary=args.llm_summary,
            no_llm_cache=args.no_llm_cache,
        )
    elif args.mode == "focused":
        run_focused(args.keywords, args.top)
    else:
        run()
    if args.explore and args.mode != "explore":
        print()
        run()