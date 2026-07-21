"""Live smoke test of baidu pipeline against real endpoints.

Three-stage test: board → search (3 hot words) → article (top 2 results).
Sequential with delays, captcha detection, raw responses saved to
``tmp/baidu_smoke/<timestamp>/`` for forensic review.

Captcha markers are heuristic — see ``CAPTCHA_MARKERS``. A body is also
flagged as captcha when it falls below the size threshold for its stage.

This is a diagnostic, not a feature. It exists to answer one question:
"what fraction of real baidu calls hit captcha today?"

Usage:
    PYTHONPATH=src uv run python scripts/probe_baidu_smoke.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from heated_topics_v3.fetcher_factory import make_baidu_fetcher  # noqa: E402
from heated_topics_v3.providers.baidu import (  # noqa: E402
    ARTICLE_URL_TEMPLATE,
    BOARD_URL,
    SEARCH_URL_TEMPLATE,
    parse_baidu_board_response,
    parse_baidu_search_response,
)

CAPTCHA_MARKERS = (
    "安全验证",
    "百度安全",
    "验证码",
    "captcha",
    "wappass.baidu.com",
    "请输入验证码",
    "verify",
)
BOARD_MIN_BYTES = 8_000
SEARCH_MIN_BYTES = 3_000
ARTICLE_MIN_BYTES = 5_000
SEARCH_DELAY_SECONDS = 8
ARTICLE_DELAY_SECONDS = 10


def is_captcha(body: str, *, min_bytes: int) -> dict[str, object]:
    flags = [m for m in CAPTCHA_MARKERS if m in body.lower() or m in body]
    return {
        "size": len(body),
        "below_size_threshold": len(body) < min_bytes,
        "matched_markers": flags,
        "is_captcha": bool(flags) or len(body) < min_bytes,
    }


def utc8_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")


def safe_slug(value: str, limit: int = 24) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", value).strip("_")
    return (cleaned or "x")[:limit]


def main() -> int:
    out_dir = ROOT / "tmp" / "baidu_smoke" / utc8_now()
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = make_baidu_fetcher(timeout=15)
    summary: dict[str, object] = {
        "started_at": utc8_now(),
        "board": {},
        "searches": [],
        "articles": [],
    }

    print("[1/3] board fetch")
    print(f"  GET {BOARD_URL}")
    try:
        body = fetcher(BOARD_URL, 15)
        (out_dir / "board.json").write_text(body, encoding="utf-8")
        captcha_info = is_captcha(body, min_bytes=BOARD_MIN_BYTES)
        items = [] if captcha_info["is_captcha"] else parse_baidu_board_response(
            body, fetched_at="", matched_query_ids=()
        )
        summary["board"] = {
            **captcha_info,
            "status": "ok",
            "top_words": [it.title for it in items[:5]],
        }
    except Exception as exc:
        summary["board"] = {"status": "error", "error": repr(exc)}
        items = []
    print(
        f"  -> status={summary['board'].get('status')}, "
        f"size={summary['board'].get('size', 0)}, "
        f"captcha={summary['board'].get('is_captcha', '?')}, "
        f"top_words={summary['board'].get('top_words', [])}"
    )

    if not summary["board"].get("top_words"):
        _save_summary(out_dir, summary)
        print("Board returned no hot words; aborting.")
        return 1

    words = summary["board"]["top_words"][:3]  # type: ignore[index]
    article_ids: list[str] = []
    for index, word in enumerate(words, start=1):
        print(f"[2/3] search #{index}: {word}")
        time.sleep(SEARCH_DELAY_SECONDS)
        url = SEARCH_URL_TEMPLATE.format(word=urllib.parse.quote(word))
        print(f"  GET {url}")
        try:
            body = fetcher(url, 15)
            (out_dir / f"search_{index}_{safe_slug(word)}.html").write_text(
                body, encoding="utf-8"
            )
            captcha_info = is_captcha(body, min_bytes=SEARCH_MIN_BYTES)
            articles = (
                [] if captcha_info["is_captcha"] else parse_baidu_search_response(
                    body, source_word=word
                )
            )
            entry = {
                **captcha_info,
                "status": "ok",
                "word": word,
                "articles_found": len(articles),
                "first_article_id": articles[0].article_id if articles else None,
            }
            if articles:
                article_ids.append(articles[0].article_id)
        except Exception as exc:
            entry = {"status": "error", "word": word, "error": repr(exc)}
        summary["searches"].append(entry)
        print(
            f"  -> status={entry.get('status')}, "
            f"size={entry.get('size', 0)}, "
            f"captcha={entry.get('is_captcha', '?')}, "
            f"articles_found={entry.get('articles_found', '?')}"
        )

    for index, article_id in enumerate(article_ids[:2], start=1):
        print(f"[3/3] article #{index}: {article_id}")
        time.sleep(ARTICLE_DELAY_SECONDS)
        url = ARTICLE_URL_TEMPLATE.format(article_id=article_id)
        print(f"  GET {url}")
        try:
            body = fetcher(url, 15)
            (out_dir / f"article_{index}_{article_id[:16]}.html").write_text(
                body, encoding="utf-8"
            )
            captcha_info = is_captcha(body, min_bytes=ARTICLE_MIN_BYTES)
            entry = {**captcha_info, "status": "ok", "article_id": article_id}
        except Exception as exc:
            entry = {"status": "error", "article_id": article_id, "error": repr(exc)}
        summary["articles"].append(entry)
        print(
            f"  -> status={entry.get('status')}, "
            f"size={entry.get('size', 0)}, "
            f"captcha={entry.get('is_captcha', '?')}"
        )

    _save_summary(out_dir, summary)
    print(f"\nDone. Summary: {out_dir / 'summary.json'}")
    return 0


def _save_summary(out_dir: Path, summary: dict[str, object]) -> None:
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())