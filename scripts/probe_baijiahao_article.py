"""Live smoke test of baijiahao article-page endpoint.

Tests ``https://baijiahao.baidu.com/s?id=<id>`` directly using two known
article IDs captured during the 2026-07-19 reconnaissance. For each ID,
two UA modes are tried: the production ``BAIDU_MOBILE_UA`` and a desktop
Chrome UA. Captcha markers + body size threshold determine whether the
response is real content.

This isolates baijiahao from the baidu search captcha that blocks the
baidu pipeline's stage 2. The question being answered: ``baijiahao.baidu.com``
article pages reachable *with* an ID, independent of search?

Usage:
    PYTHONPATH=src uv run python scripts/probe_baijiahao_article.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from heated_topics_v3.fetcher_factory import BAIDU_MOBILE_UA  # noqa: E402

CAPTCHA_MARKERS = (
    "百度安全验证",
    "安全验证",
    "验证码",
    "captcha",
    "wappass.baidu.com",
    "请输入验证码",
)
ARTICLE_MIN_BYTES = 5_000
ARTICLE_IDS = (
    "1871059716908391735",
    "1871008630857219066",
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def utc8_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")


def fetch(url: str, ua: str, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", ua)
    req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
    req.add_header("Referer", "https://m.baidu.com/s")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception:
            return exc.code, ""


def is_captcha(body: str) -> dict[str, object]:
    flags = [m for m in CAPTCHA_MARKERS if m in body]
    return {
        "size": len(body),
        "matched_markers": flags,
        "is_captcha": bool(flags) or len(body) < ARTICLE_MIN_BYTES,
    }


def main() -> int:
    out_dir = ROOT / "tmp" / "baijiahao_smoke" / utc8_now()
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {"started_at": utc8_now(), "results": []}

    for article_id in ARTICLE_IDS:
        for label, ua in (("mobile", BAIDU_MOBILE_UA), ("desktop", DESKTOP_UA)):
            url = f"https://baijiahao.baidu.com/s?id={article_id}"
            print(f"GET [{label}] {url}")
            try:
                status, body = fetch(url, ua)
            except Exception as exc:
                summary["results"].append(
                    {"article_id": article_id, "ua": label, "error": repr(exc)}
                )
                print(f"  -> ERROR {exc!r}")
                continue
            slug = f"{label}_{article_id[:12]}.html"
            (out_dir / slug).write_text(body, encoding="utf-8")
            verdict = is_captcha(body)
            entry = {
                "article_id": article_id,
                "ua": label,
                "http_status": status,
                **verdict,
            }
            summary["results"].append(entry)
            print(
                f"  -> http={status}, size={verdict['size']}, "
                f"captcha={verdict['is_captcha']}, markers={verdict['matched_markers']}"
            )
            time.sleep(6)

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDone. Summary: {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())