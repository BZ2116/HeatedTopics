"""Reference probe kept after Baidu hot-word source implementation.

Captures the discovery path that landed on
`https://top.baidu.com/api/board?platform=wise&page=realtime` plus the
secondary endpoints used during planning:

- `https://m.baidu.com/s?word=<encoded>` — mobile Baidu search page.
  Heavily rate-limited; expect ~1 captcha per request after a few calls.
- `https://baijiahao.baidu.com/s?id=<id>` — article page; HTML is large
  but well-structured for `parse_baidu_article_response` to consume.

Usage:
    PYTHONPATH=src uv run python scripts/probe_baidu_board.py

This is a diagnostic, not a feature. Its existence is documented in
`docs/superpowers/specs/2026-07-19-baidu-hotword-source-design.md`.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
BOARD_URL = "https://top.baidu.com/api/board?platform=wise&page=realtime"


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "tmp" / "baidu_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(BOARD_URL, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    snapshot = out_dir / f"board_{int(time.time())}.json"
    snapshot.write_text(body, encoding="utf-8")
    print(f"snapshot: {snapshot}")
    print(json.dumps(json.loads(body)["data"]["cards"][0]["content"][0]["content"][:3], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())