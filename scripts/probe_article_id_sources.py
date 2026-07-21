"""Recon probe for alternative article_id sources.

The baidu pipeline's stage 2 (``m.baidu.com/s?word=...``) is blocked by
captcha — search returns 100% captcha pages. This probe tests candidate
endpoints that might supply baijiahao article_ids without going through
the captcha'd search:

  - baidu desktop search (``www.baidu.com/s?wd=...``)
  - baidu news search (``www.baidu.com/s?wd=...&tn=news``,
    ``m.news.baidu.com/news?word=...``)
  - top.baidu.com board variants (``platform=pc``, ``tab=...``)
  - baijiahao sitemap (``baijiahao.baidu.com/sitemap.xml``)
  - baijiahao homepage pattern (``baijiahao.baidu.com/``)

Each endpoint is hit once with the production fetcher. Responses are
saved to ``tmp/article_id_recon/<timestamp>/`` and a summary.json is
written. The script does NOT retry — captcha accumulates per IP, so
hammering is counterproductive.

Usage:
    PYTHONPATH=src uv run python scripts/probe_article_id_sources.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from heated_topics_v3.fetcher_factory import make_baidu_fetcher  # noqa: E402

CAPTCHA_MARKERS = (
    "百度安全验证",
    "安全验证",
    "验证码",
    "captcha",
    "wappass.baidu.com",
    "请输入验证码",
)
HOT_WORD = "人工智能"
DELAY_SECONDS = 6


def utc8_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")


def safe_slug(value: str, limit: int = 32) -> str:
    out = "".join(c if c.isalnum() or "一" <= c <= "鿿" else "_" for c in value)
    return (out or "x")[:limit]


def classify(body: str) -> dict[str, object]:
    size = len(body)
    markers = [m for m in CAPTCHA_MARKERS if m in body]
    has_bjh_link = "baijiahao.baidu.com/s?id=" in body
    has_search_hints = any(
        marker in body for marker in ("百度为您找到相关结果", "的相关资讯", "相关新闻")
    )
    return {
        "size": size,
        "captcha_markers": markers,
        "is_captcha": bool(markers) or size < 1500,
        "has_baijiahao_link": has_bjh_link,
        "looks_like_search_results": has_search_hints,
    }


def probe(url: str, fetcher, label: str, out_dir: Path, summary: dict) -> None:
    print(f"GET [{label}] {url}")
    time.sleep(DELAY_SECONDS)
    try:
        body = fetcher(url, 15)
    except Exception as exc:
        summary[label] = {"url": url, "error": repr(exc)}
        print(f"  -> ERROR {exc!r}")
        return
    slug = safe_slug(label)
    (out_dir / f"{slug}.html").write_text(body, encoding="utf-8")
    verdict = classify(body)
    entry = {"url": url, **verdict}
    summary[label] = entry
    print(
        f"  -> size={verdict['size']}, captcha={verdict['is_captcha']}, "
        f"bjh_link={verdict['has_baijiahao_link']}"
    )


def main() -> int:
    out_dir = ROOT / "tmp" / "article_id_recon" / utc8_now()
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = make_baidu_fetcher(timeout=15)
    summary: dict[str, object] = {"started_at": utc8_now(), "hot_word": HOT_WORD}
    encoded_word = urllib.parse.quote(HOT_WORD)

    endpoints = [
        ("baidu_desktop_search", f"https://www.baidu.com/s?wd={encoded_word}"),
        ("baidu_news_search", f"https://www.baidu.com/s?wd={encoded_word}&tn=news"),
        ("baidu_news_tab", f"https://www.baidu.com/s?wd={encoded_word}&tn=news&rtt=4"),
        ("m_news_baidu", f"https://m.news.baidu.com/news?word={encoded_word}"),
        ("top_baidu_pc_board", "https://top.baidu.com/api/board?platform=pc&page=realtime"),
        ("top_baidu_wise_finance", "https://top.baidu.com/api/board?platform=wise&page=finance"),
        ("bjh_sitemap_xml", "https://baijiahao.baidu.com/sitemap.xml"),
        ("bjh_sitemap_index", "https://baijiahao.baidu.com/sitemap"),
    ]

    for label, url in endpoints:
        probe(url, fetcher, label, out_dir, summary)

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDone. Summary: {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())