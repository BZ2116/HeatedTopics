"""One-shot cookie harvester for Toutiao using Playwright + DrissionPage.

Both browsers visit https://www.toutiao.com/ to receive the standard first-
party cookies (ttwid, msToken, etc), then we union their cookie sets and
merge with whatever's already in the on-disk cookie file.

Output: a single semicolon-separated "Cookie:" header string written to
`scripts/.toutiao_cookie`. Read by `run_pipeline.py` (and any other
caller passing that path to `fetcher_factory.make_search_fetcher`).

Re-run when the existing cookie set stops producing search results.

Usage:
    python harvest_cookies.py                # both browsers + keep existing
    python harvest_cookies.py --fresh        # both browsers + replace existing
    python harvest_cookies.py --pw-only      # just Playwright, keep existing
    python harvest_cookies.py --dp-only      # just DrissionPage, keep existing
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Project root (parent of scripts/)
ROOT = Path(__file__).resolve().parent.parent
COOKIE_PATH = ROOT / ".toutiao_cookie"
TODAY_SECONDS = 35
TODAY_HOME = "https://www.toutiao.com/"


# ---------- harvesters ----------

def harvest_with_playwright() -> dict[str, str]:
    """Headless Chromium visits homepage, sleep, dump cookies. Returns {name: value}."""
    from playwright.sync_api import sync_playwright

    out: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = context.new_page()
        page.goto(TODAY_HOME, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        for c in context.cookies():
            name = c.get("name")
            value = c.get("value")
            if name and value:
                out[str(name)] = str(value)
        browser.close()
    return out


def harvest_with_drissionpage() -> dict[str, str]:
    """Headless Chromium via DrissionPage, same drill. Cookies filtered to dict."""
    from DrissionPage import ChromiumPage

    out: dict[str, str] = {}
    page = ChromiumPage()
    try:
        page.get(TODAY_HOME, timeout=30)
        page.wait(4)
        cookies = page.cookies()
        for c in cookies:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            value = c.get("value")
            if name and value:
                out[str(name)] = str(value)
    finally:
        page.quit()
    return out


# ---------- file handling ----------

def read_existing_cookie_file(path: Path) -> dict[str, str]:
    """Parse the semicolon-separated Cookie: header into {name: value}."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split("; "):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            out[name] = value
    return out


def write_cookie_file(path: Path, cookies: dict[str, str]) -> None:
    header = "; ".join(f"{k}={v}" for k, v in sorted(cookies.items()))
    path.write_text(header, encoding="utf-8")


def safe_harvest(name: str, fn) -> dict[str, str]:
    print(f"\n[{name}] launching...", flush=True)
    started = time.time()
    try:
        cookies = fn()
        print(f"[{name}] ok in {time.time() - started:.1f}s — {len(cookies)} cookies")
        return cookies
    except Exception as exc:
        print(f"[{name}] FAILED in {time.time() - started:.1f}s — {type(exc).__name__}: {exc}")
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest Toutiao cookies via headless browsers")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fresh", action="store_true", help="Replace existing cookies, don't merge")
    mode.add_argument("--pw-only", action="store_true", help="Skip DrissionPage harvest")
    mode.add_argument("--dp-only", action="store_true", help="Skip Playwright harvest")
    args = parser.parse_args()

    use_pw = not args.dp_only
    use_dp = not args.pw_only

    print(f"cookie file: {COOKIE_PATH}")
    print(f"mode: {'fresh' if args.fresh else 'merge-with-existing'}")
    print(f"browsers: playwright={use_pw}, drissionpage={use_dp}")

    existing = read_existing_cookie_file(COOKIE_PATH) if not args.fresh else {}
    print(f"existing: {len(existing)} cookies: {sorted(existing.keys())}")

    pw = safe_harvest("playwright", harvest_with_playwright) if use_pw else {}
    dp = safe_harvest("drissionpage", harvest_with_drissionpage) if use_dp else {}

    merged = dict(existing)
    merged.update(pw)
    merged.update(dp)

    print("\n--- merged set ---")
    print(json.dumps({k: (v[:24] + "..." if len(v) > 24 else v) for k, v in sorted(merged.items())}, ensure_ascii=False, indent=2))
    print(f"total: {len(merged)} cookies")

    write_cookie_file(COOKIE_PATH, merged)
    size = COOKIE_PATH.stat().st_size
    print(f"\nwrote {size} bytes to {COOKIE_PATH}")
    print("OK.")


if __name__ == "__main__":
    sys.exit(main())
