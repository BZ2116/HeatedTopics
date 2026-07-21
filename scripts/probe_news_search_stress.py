"""Stress test: how many sequential baidu news searches before captcha?

Uses ``https://www.baidu.com/s?wd=WORD&tn=news`` with 6s delay between
calls. Outputs captcha rate to ``tmp/news_search_stress/<ts>/summary.json``.

Run once after probe_article_id_sources.py to confirm the news search
endpoint stays reachable under repeated calls.
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

CAPTCHA_MARKERS = ("百度安全验证", "安全验证", "验证码", "wappass.baidu.com")
DELAY_SECONDS = 6
N_CALLS = 10
WORDS = ("人工智能", "习近平", "世界杯", "奥运会", "经济", "科技", "教育",
         "医疗", "金融", "文化")[:N_CALLS]


def utc8_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")


def main() -> int:
    out_dir = ROOT / "tmp" / "news_search_stress" / utc8_now()
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = make_baidu_fetcher(timeout=15)
    summary: dict[str, object] = {"started_at": utc8_now(), "calls": []}

    for i, word in enumerate(WORDS, start=1):
        url = f"https://www.baidu.com/s?wd={urllib.parse.quote(word)}&tn=news"
        print(f"[{i}/{N_CALLS}] {word}")
        time.sleep(DELAY_SECONDS)
        try:
            body = fetcher(url, 15)
        except Exception as exc:
            summary["calls"].append({"word": word, "error": repr(exc)})
            print(f"  ERROR {exc!r}")
            continue
        size = len(body)
        captcha = any(m in body for m in CAPTCHA_MARKERS) or size < 1500
        bjh_count = body.count("baijiahao.baidu.com/s?id=")
        summary["calls"].append(
            {"word": word, "size": size, "captcha": captcha, "bjh_link_count": bjh_count}
        )
        print(f"  -> size={size}, captcha={captcha}, bjh_links={bjh_count}")

    captcha_count = sum(
        1 for c in summary["calls"] if c.get("captcha") is True
    )
    summary["captcha_rate"] = captcha_count / max(1, len(summary["calls"]))

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nCaptcha rate: {captcha_count}/{len(summary['calls'])}")
    print(f"Summary: {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())