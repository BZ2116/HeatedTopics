"""Three-stage fetcher factory for Toutiao search API.

Returns a single fetcher callable that progressively falls back through:
  1. urllib + harvested cookies (default, fast, low-fingerprint)
  2. Playwright live Chromium (when stage 1 fails 3 consecutive calls)
  3. DrissionPage live Chromium (when stage 2 also fails)

Stages auto-promote when the higher stage recovers. Pacing between calls
follows jitter + batch-pause rules. Every call is logged to a JSON file.

Falls back automatically when cookies haven't been harvested yet (run
`python scripts/harvest_cookies.py`).

Response shape: Toutiao sometimes wraps JSON inside an HTML envelope
(`<html><body><pre>{...}</pre></body></html>`). The fetcher strips that
wrapper before returning so callers can `json.loads` directly.
"""
from __future__ import annotations

import html
import json
import math
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from heated_topics_v3.baidu_retry import BaiduRetryPolicy, with_retry


UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
]

# A response is considered "real" if it has positive count and substantial body
EMPTY_HINT_RE = re.compile(r"抱歉.*未找到|未找到.*结果|暂无可用")
COUNT_RE = re.compile(r'"count"\s*:\s*(\d+)')

# Pacing
JITTER_MIN_SECONDS = 4.0
JITTER_MAX_SECONDS = 8.0
BATCH_SIZE = 5
BATCH_REST_SECONDS = 60.0

# Stage ladder transitions
DEMOTE_AFTER_FAILS = 3
PROMOTE_AFTER_SUCCEED = 3

# Failure threshold that disables search path entirely
DISABLE_AT_FAILURE_RATE = 0.5
DISABLE_MIN_SAMPLES = 5

# Body length threshold below which we consider the body an Argus empty/captcha page
MIN_BODY_BYTES = 8000

STAGE_URLLIB = "urllib+cookies"
STAGE_PLAYWRIGHT = "playwright-live"
STAGE_DRISSION = "drissionpage-live"


def _strip_html_wrapper(body: str) -> str:
    """If body is HTML-wrapped JSON, extract and unescape the JSON inside.

    Returns the original body unchanged if it isn't an HTML envelope.
    The wrapped JSON uses HTML entities (&amp; &lt; &gt; etc.) inside
    the embedded JSON text, so we html.unescape before returning.
    """
    stripped = body.lstrip()
    if not stripped.startswith("<"):
        return body
    pre_open = stripped.find("<pre")
    if pre_open == -1:
        return body
    gt = stripped.find(">", pre_open)
    if gt == -1:
        return body
    pre_close = stripped.rfind("</pre>")
    if pre_close == -1 or pre_close < gt:
        return body
    inner = stripped[gt + 1 : pre_close]
    try:
        return html.unescape(inner)
    except Exception:
        return body


def _unwrap_response(body: str) -> str:
    """Strip Toutiao's HTML envelope from JSON responses, if present."""
    return _strip_html_wrapper(body)


@dataclass
class FetcherLog:
    path: Path
    entries: deque

    def append(self, **fields) -> None:
        rec = {"ts": int(time.time() * 1000), **fields}
        self.entries.append(rec)
        self._flush()

    def _flush(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(list(self.entries), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


class SearchFetcher:
    """Internal class implementing the stage ladder. Exposed via factory."""

    def __init__(
        self,
        cookie_path: Path,
        log_path: Path,
        timeout: int = 30,
        random_seed: int | None = None,
        paced: bool = True,
    ) -> None:
        self.cookie_path = cookie_path
        self.timeout = timeout
        self.paced = paced
        self._log = FetcherLog(path=log_path, entries=deque(maxlen=500))
        self._random = random.Random(random_seed)
        self._cookies: str | None = None
        self._last_url: str | None = None
        self._calls_in_batch = 0
        self._consec_success: dict[str, int] = {STAGE_URLLIB: 0, STAGE_PLAYWRIGHT: 0, STAGE_DRISSION: 0}
        self._consec_fail: dict[str, int] = {STAGE_URLLIB: 0, STAGE_PLAYWRIGHT: 0, STAGE_DRISSION: 0}
        self._active_stage = STAGE_URLLIB
        self._disabled = False
        self._playwright = None
        self._playwright_ctx = None
        self._playwright_page = None
        self._drission = None
        self._recent_outcomes: deque[bool] = deque(maxlen=DISABLE_MIN_SAMPLES)

    # ---------- public entry ----------
    def __call__(self, url: str, timeout: int | None = None) -> str:
        if self._disabled:
            raise RuntimeError("fetcher disabled due to high failure rate; run harvest_cookies.py")
        self._pace()
        timeout = timeout or self.timeout
        body, stage, info = self._fetch_with_active(url, timeout)
        body = _unwrap_response(body)
        self._recent_outcomes.append(info["ok"])
        self._log.append(
            url=url,
            stage=stage,
            status=info.get("status"),
            bytes=info.get("bytes"),
            count=info.get("count"),
            suspect=info.get("suspect"),
            latency_ms=int(info.get("elapsed", 0) * 1000),
            ok=info.get("ok"),
            error=info.get("error"),
        )
        self._last_url = url
        if not info["ok"]:
            self._consec_fail[stage] += 1
            self._consec_success[stage] = 0
            self._maybe_demote()
        else:
            self._consec_success[stage] += 1
            self._consec_fail[stage] = 0
            self._maybe_promote()
        self._maybe_disable_search()
        return body

    # ---------- pacing ----------
    def _pace(self) -> None:
        if not self.paced:
            return
        if self._last_url is None:
            return
        self._calls_in_batch += 1
        if self._calls_in_batch >= BATCH_SIZE:
            self._calls_in_batch = 0
            time.sleep(BATCH_REST_SECONDS)
        else:
            time.sleep(self._random.uniform(JITTER_MIN_SECONDS, JITTER_MAX_SECONDS))

    # ---------- stage dispatch ----------
    def _fetch_with_active(self, url: str, timeout: int) -> tuple[str, str, dict]:
        ladder = [STAGE_URLLIB, STAGE_PLAYWRIGHT, STAGE_DRISSION]
        active_idx = ladder.index(self._active_stage)
        deadline = time.monotonic() + timeout
        last_info: dict = {"ok": False, "error": "no attempt"}
        last_body = ""
        for stage in ladder[active_idx:]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            stage_timeout = max(1, math.ceil(remaining))
            body, info = self._fetch_one(stage, url, stage_timeout)
            info["suspect"] = self._is_suspect(body, info)
            info["ok"] = not info["suspect"] and not info.get("error")
            if info["ok"]:
                return body, stage, info
            last_body = body
            last_info = info
        return last_body, ladder[active_idx], last_info

    def _fetch_one(self, stage: str, url: str, timeout: int) -> tuple[str, dict]:
        started = time.time()
        info: dict = {"stage": stage, "elapsed": 0.0}
        try:
            if stage == STAGE_URLLIB:
                body = self._fetch_urllib(url, timeout)
            elif stage == STAGE_PLAYWRIGHT:
                body = self._fetch_playwright(url, timeout)
            elif stage == STAGE_DRISSION:
                body = self._fetch_drission(url, timeout)
            else:
                raise RuntimeError(f"unknown stage {stage}")
            info["elapsed"] = time.time() - started
            info["status"] = 200
            info["bytes"] = len(body)
            info["count"] = self._extract_count(body)
            return body, info
        except Exception as exc:
            info["elapsed"] = time.time() - started
            info["error"] = repr(exc)
            return "", info

    def _fetch_urllib(self, url: str, timeout: int) -> str:
        cookies = self._load_cookies()
        req = urllib.request.Request(url)
        ua = self._random.choice(UA_POOL)
        req.add_header("User-Agent", ua)
        req.add_header("Accept", "application/json, text/html, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        req.add_header("Referer", "https://www.toutiao.com/")
        if cookies:
            req.add_header("Cookie", cookies)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _fetch_playwright(self, url: str, timeout: int) -> str:
        if self._playwright is None:
            self._lazy_init_playwright()
        assert self._playwright_page is not None
        self._playwright_page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        return self._playwright_page.content()

    def _fetch_drission(self, url: str, timeout: int) -> str:
        if self._drission is None:
            from DrissionPage import ChromiumPage
            page = ChromiumPage()
            self._drission = page
        page = self._drission
        page.get(url, timeout=timeout)
        return page.html

    def _lazy_init_playwright(self) -> None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=self._random.choice(UA_POOL),
            locale="zh-CN",
        )
        cookies = self._load_cookies()
        if cookies:
            ctx.add_cookies(self._parse_cookies_for_playwright(cookies))
        page = ctx.new_page()
        self._playwright = pw
        self._playwright_ctx = ctx
        self._playwright_page = page

    def _parse_cookies_for_playwright(self, header: str) -> list[dict]:
        """Convert Cookie: header string to Playwright's cookie list."""
        out: list[dict] = []
        for part in header.split("; "):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            out.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".toutiao.com",
                "path": "/",
            })
        return out

    # ---------- cookies ----------
    def _load_cookies(self) -> str:
        if self._cookies is not None:
            return self._cookies
        if not self.cookie_path.exists():
            self._cookies = ""
            return self._cookies
        raw = self.cookie_path.read_text(encoding="utf-8").strip()
        self._cookies = raw
        return self._cookies

    # ---------- failure detection ----------
    @staticmethod
    def _extract_count(body: str) -> int | None:
        m = COUNT_RE.search(body)
        return int(m.group(1)) if m else None

    @staticmethod
    def _is_suspect(body: str, info: dict) -> bool:
        if not body:
            return True
        if len(body) < MIN_BODY_BYTES:
            return True
        if info.get("error"):
            return True
        if EMPTY_HINT_RE.search(body):
            return True
        count = SearchFetcher._extract_count(body)
        if count is not None and count == 0:
            return True
        return False

    # ---------- stage transitions ----------
    def _maybe_demote(self) -> None:
        if self._consec_fail[self._active_stage] >= DEMOTE_AFTER_FAILS:
            if self._active_stage == STAGE_URLLIB:
                self._active_stage = STAGE_PLAYWRIGHT
                print("[fetcher] demote → playwright-live", flush=True)
            elif self._active_stage == STAGE_PLAYWRIGHT:
                self._active_stage = STAGE_DRISSION
                print("[fetcher] demote → drissionpage-live", flush=True)

    def _maybe_promote(self) -> None:
        if self._active_stage == STAGE_DRISSION:
            if self._consec_success[STAGE_DRISSION] >= PROMOTE_AFTER_SUCCEED:
                self._active_stage = STAGE_PLAYWRIGHT
                self._consec_success[STAGE_PLAYWRIGHT] = PROMOTE_AFTER_SUCCEED  # don't immediately demote again
                print("[fetcher] promote → playwright-live", flush=True)
        if self._active_stage == STAGE_PLAYWRIGHT:
            if self._consec_success[STAGE_PLAYWRIGHT] >= PROMOTE_AFTER_SUCCEED:
                self._active_stage = STAGE_URLLIB
                print("[fetcher] promote → urllib+cookies", flush=True)

    def _maybe_disable_search(self) -> None:
        if len(self._recent_outcomes) < DISABLE_MIN_SAMPLES:
            return
        fail_rate = 1.0 - sum(self._recent_outcomes) / len(self._recent_outcomes)
        if fail_rate >= DISABLE_AT_FAILURE_RATE:
            print(
                f"[fetcher] DISABLE — failure rate {fail_rate:.0%} >= {DISABLE_AT_FAILURE_RATE:.0%}. "
                "Switch pipeline to hot-board-only.",
                flush=True,
            )
            self._disabled = True

    # ---------- diagnostics ----------
    @property
    def stage(self) -> str:
        return self._active_stage

    @property
    def disabled(self) -> bool:
        return self._disabled


def make_search_fetcher(
    *,
    cookie_path: Path | str,
    log_path: Path | str,
    timeout: int = 30,
    dump_dir: Path | str | None = None,
    paced: bool = True,
) -> Callable[[str, int], str]:
    """Return a synchronous fetcher matching the pipeline's signature.

    Args:
        cookie_path: Path to a Cookie: header string file produced by
            `scripts/harvest_cookies.py`.
        log_path: Path to write per-call JSON diagnostics.
        timeout: Default per-request timeout in seconds.
        paced: Apply legacy jitter and batch rests between calls.
        dump_dir: Optional directory to dump each raw response body, named
            by call timestamp + sanitized URL keyword. For diagnostics only.

    Returns:
        Callable accepting `(url, timeout_seconds)` and returning response
        text. Pipeline can pass this directly to `run_toutiao_pipeline_v2(..., fetcher=...)`.
    """
    instance = SearchFetcher(
        cookie_path=Path(cookie_path),
        log_path=Path(log_path),
        timeout=timeout,
        paced=paced,
    )

    if dump_dir is not None:
        dump_root = Path(dump_dir)
        dump_root.mkdir(parents=True, exist_ok=True)

        def _dump(url: str, body: str) -> None:
            try:
                m = re.search(r"keyword=([^&]+)", url)
                kw = urllib.parse.unquote(m.group(1)) if m else "unknown"
                ts = int(time.time() * 1000)
                path = dump_root / f"{ts}_{_slug_for_path(kw)}.json"
                path.write_text(body, encoding="utf-8")
            except OSError:
                pass

    def _fetcher(url: str, timeout_seconds: int = timeout) -> str:
        body = instance(url, timeout_seconds)
        if dump_dir is not None:
            _dump(url, body)
        return body

    _fetcher.stage = lambda: instance.stage  # type: ignore[attr-defined]
    _fetcher.disabled = lambda: instance.disabled  # type: ignore[attr-defined]
    return _fetcher


def _slug_for_path(value: str) -> str:
    return re.sub(r"[^\w一-鿿\-]+", "_", value).strip("_")[:40]


# ---------------------------------------------------------------------------
# Baidu fetcher — plain urllib with mobile UA, no cookies, no stage ladder.
# ---------------------------------------------------------------------------

BAIDU_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


def _referer_for(url: str) -> str | None:
    host = urllib.parse.urlparse(url).netloc
    if host.endswith("top.baidu.com"):
        return "https://top.baidu.com/"
    if host.endswith("www.baidu.com"):
        return "https://www.baidu.com/"
    if host.endswith("baijiahao.baidu.com"):
        return "https://www.baidu.com/s"
    return None


def make_baidu_fetcher(
    *,
    timeout: int = 15,
    log_path: Path | str | None = None,
    retry_policy: BaiduRetryPolicy | None = None,
) -> Callable[[str, int], str]:
    """Return a synchronous fetcher for Baidu board / search / article URLs.

    Plain urllib with mobile UA and a per-host Referer. No cookies, no stage
    ladder, no pacing — Baidu's mobile endpoints don't require any of that.

    On HTTPError / URLError, the error body is returned as a string so callers
    can inspect it (e.g. detect a captcha HTML page). Non-recoverable errors
    (no body, or non-HTML errors) are re-raised.
    """

    def _fetcher(url: str, timeout_seconds: int = timeout) -> str:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", BAIDU_MOBILE_UA)
        req.add_header("Accept", "application/json, text/html, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        referer = _referer_for(url)
        if referer is not None:
            req.add_header("Referer", referer)
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if body and ("<html" in body.lower() or "<!doctype" in body.lower()):
                return body
            raise
        except urllib.error.URLError as exc:
            raise

    return with_retry(_fetcher, retry_policy or BaiduRetryPolicy())


def _parse_cookie_header(header: str) -> dict[str, str]:
    """Parse a Cookie: header string into a dict for curl_cffi."""
    out: dict[str, str] = {}
    for part in header.split("; "):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        out[name.strip()] = value.strip()
    return out


def make_baidu_article_fetcher(
    *,
    cookie_path: Path | str,
    log_path: Path | str | None = None,
    retry_policy: BaiduRetryPolicy | None = None,
    timeout: int = 20,
) -> Callable[[str, int], str]:
    """Return a fetcher for baijiahao article pages.

    baijiahao's anti-bot shell returns the full article body (with
    ``window.jsonData`` embedded) only when the request carries a valid Baidu
    cookie AND a Chrome TLS fingerprint. Plain urllib fails the TLS check;
    this factory wraps curl_cffi with ``impersonate="chrome120"``.

    Args:
        cookie_path: Path to a Cookie: header file written by
            ``scripts/harvest_baidu_cookie.py``.
        log_path: Optional JSON log path (per-call diagnostics).
        retry_policy: Retry policy for transient errors.
        timeout: Default per-request timeout in seconds.

    Returns:
        Callable accepting ``(url, timeout_seconds)`` and returning response
        text. Pipeline passes this as the ``article_fetch`` callable.
    """
    from curl_cffi import requests as cffi_requests

    cookie_header = Path(cookie_path).read_text(encoding="utf-8").strip()
    cookie_dict = _parse_cookie_header(cookie_header)

    def _fetcher(url: str, timeout_seconds: int = timeout) -> str:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": BAIDU_MOBILE_UA,
        }
        referer = _referer_for(url)
        if referer is not None:
            headers["Referer"] = referer
        resp = cffi_requests.get(
            url,
            impersonate="chrome120",
            cookies=cookie_dict,
            timeout=timeout_seconds,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.text

    return with_retry(_fetcher, retry_policy or BaiduRetryPolicy())


BILIBILI_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def make_bilibili_fetcher(
    *,
    timeout: int = 20,
    log_path: Path | str | None = None,
    cookie_path: Path | str | None = None,
    retry_policy: BaiduRetryPolicy | None = None,
) -> Callable[[str, int], str]:
    """GET-only fetcher for Bilibili search-API JSON and read-page HTML.

    桌面 UA + Referer https://www.bilibili.com。可选 buvid3 cookie。WBI 签名
    不在此层——provider 已签好完整 URL。
    """
    cookie_header = ""
    if cookie_path is not None and Path(cookie_path).exists():
        cookie_header = Path(cookie_path).read_text(encoding="utf-8").strip()

    def _fetcher(url: str, timeout_seconds: int = timeout) -> str:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", BILIBILI_DESKTOP_UA)
        req.add_header("Accept", "application/json, text/html, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        req.add_header("Referer", "https://www.bilibili.com")
        if cookie_header:
            req.add_header("Cookie", cookie_header)
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read().decode("utf-8", errors="replace")

    return with_retry(_fetcher, retry_policy or BaiduRetryPolicy())


JUEJIN_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def make_juejin_fetcher(
    *,
    timeout: int = 20,
    log_path: Path | str | None = None,
    retry_policy: BaiduRetryPolicy | None = None,
) -> Callable[[str, int, dict | None], str]:
    """GET/POST 二合一 fetcher。body 非空 → POST application/json。"""

    def _fetcher(url: str, timeout_seconds: int = timeout, body: dict | None = None) -> str:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        req.add_header("User-Agent", JUEJIN_DESKTOP_UA)
        req.add_header("Accept", "application/json, text/html, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        req.add_header("Referer", "https://juejin.cn")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _with_retry_3arg(url: str, timeout_seconds: int = timeout, body: dict | None = None) -> str:
        policy = retry_policy or BaiduRetryPolicy()
        attempt = 0
        while True:
            try:
                return _fetcher(url, timeout_seconds, body)
            except BaseException as exc:
                from heated_topics_v3.baidu_retry import is_retryable
                attempt += 1
                if attempt >= policy.max_attempts or not is_retryable(exc):
                    raise
                time.sleep(min(policy.base_delay * 2 ** (attempt - 1), policy.max_delay))

    return _with_retry_3arg


SINA_NEWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
NETEASE_NEWS_UA = SINA_NEWS_UA


def _news_referer_for(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc
    if host.endswith("sina.com.cn"):
        return "https://news.sina.com.cn/"
    if host.endswith("163.com"):
        return "https://www.163.com/"
    return ""


def make_sina_news_fetcher(
    *,
    timeout: int = 20,
    log_path: Path | str | None = None,
    retry_policy: BaiduRetryPolicy | None = None,
) -> Callable[[str, int], str]:
    """GET-only fetcher for Sina News hot list / search / article HTML.

    Plain urllib + desktop Chrome UA + zh-CN Accept-Language + sina Referer.
    No cookies, no stage ladder. Sina's endpoints respond to plain GET.
    """

    def _fetcher(url: str, timeout_seconds: int = timeout) -> str:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", SINA_NEWS_UA)
        req.add_header("Accept", "application/json, text/html, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        referer = _news_referer_for(url)
        if referer:
            req.add_header("Referer", referer)
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read().decode("utf-8", errors="replace")

    return with_retry(_fetcher, retry_policy or BaiduRetryPolicy())


def make_netease_news_fetcher(
    *,
    timeout: int = 20,
    log_path: Path | str | None = None,
    retry_policy: BaiduRetryPolicy | None = None,
) -> Callable[[str, int], str]:
    """GET-only fetcher for NetEase News hot list / search / article HTML.

    Plain urllib + desktop Chrome UA + zh-CN Accept-Language + 163 Referer.
    No cookies, no stage ladder.
    """

    def _fetcher(url: str, timeout_seconds: int = timeout) -> str:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", NETEASE_NEWS_UA)
        req.add_header("Accept", "application/json, text/html, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        referer = _news_referer_for(url)
        if referer:
            req.add_header("Referer", referer)
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read().decode("utf-8", errors="replace")

    return with_retry(_fetcher, retry_policy or BaiduRetryPolicy())
