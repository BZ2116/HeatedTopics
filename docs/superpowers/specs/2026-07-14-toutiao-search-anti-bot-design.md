# Toutiao Search Anti-Bot Design

## Purpose

Toutiao's `https://so.toutiao.com/search/?...` API is guarded by ByteDance Argus. Bare `urllib` requests return `count=0` with the "抱歉，未找到相关结果" page even when paired with one or two hand-copied cookies (verified 2026-07-14). The pipeline must still drive persona-keyword search through this endpoint, so we need a fetcher that survives Argus long enough to deliver ≥5 hot candidates per persona run.

## Current Problem

Three things were tried and failed:

| Attempt | Result |
|---|---|
| Bare `urllib` + `Accept`/`User-Agent`/`Referer` headers | All 5 test keywords → `count=0`, "抱歉" page |
| Add `ttwid` cookie (one key) | 1 of 5 keywords (世界杯) recovered `count=1`, the other 4 still `count=0` |
| Add `ttwid` + `msToken` (two keys) | All 5 keywords → `count=0`; runs are flaky (灰度 of 0 vs 1 result with no cookies) |

Diagnosis: Argus looks at more than cookies — UA fingerprint, request cadence, IP reputation, and possibly missing CSRF/security tokens. A bare `urllib` request can never assemble enough signals to look like a real browser.

## Design

### Two-tools-in-one fetcher, harvest-then-fallback

We install **both** Playwright and DrissionPage because they bring different strengths:

| Tool | Browser footprint | Cost | Strength for Toutiao |
|---|---|---|---|
| Playwright | Downloads its own ~150 MB Chromium | `pip install playwright` + `playwright install chromium` | Solid default, predictable |
| DrissionPage | Uses system-installed Edge/Chrome | `pip install drissionpage` | Designed for Chinese anti-bot stacks (字节/腾讯/百度) |

Both produce cookie jars that look identical to a real browser session. We keep both because if Argus patches itself against one headless fingerprint, the other may still pass.

### Cookie harvest (one-shot)

`tmp_3users_test/harvest_cookies.py`:

1. Run Playwright headless, navigate to `https://www.toutiao.com/`, sleep 4s, dump `context.cookies()` to list.
2. Run DrissionPage (headless = system Edge/Chrome), same steps.
3. Union both cookie lists, dedupe by `(name, domain, path)`.
4. Append to (or merge into) any existing `tmp_3users_test/.toutiao_cookie` set.
5. Write back as a single `Cookie:` header string semicolon-separated.

Re-run when the cookie set is stale (≥3 consecutive fetcher failures at the urllib stage). Harvest is manual, not auto-triggered, to keep the pipeline deterministic.

### Fetcher factory

`src/heated_topics_v3/fetcher_factory.py`:

```
make_search_fetcher(*, cookie_path, log_path, timeout=30) -> Callable[[str], str]
```

Returns a single `fetcher(url)` callable with this stage ladder:

1. **Stage 1 — urllib + cookies** (default, fastest)
   - Read cookie file on first call, cached for the lifetime of the fetcher.
   - Set full Chrome request header stack: `User-Agent` (rotated from a 5-pool), `Accept`, `Accept-Language`, `Accept-Encoding`, `Referer`, `Sec-Fetch-*`, `sec-ch-ua*`.
   - Match keyword query against `count=0 + sorry=True` detection.

2. **Stage 2 — Playwright live** (when Stage 1 fails 3 consecutive calls)
   - Lazy-init a single Chromium context with the harvested cookies.
   - `await page.goto(url, wait_until="networkidle")` for each fetch.
   - Return `page.content()`.

3. **Stage 3 — DrissionPage live** (when Stage 2 also fails)
   - Lazy-init a DrissionPage Chromium tab with the harvested cookies.
   - `.get(url)` per fetch.

Stages auto-promote / auto-demote based on a sliding window of success rate. A stage that recovers (3 consecutive successes) can move back up.

### Pacing (between fetcher calls)

The pipeline wraps each search keyword with a `pause()` callback controlled by the factory:

| Rule | Value |
|---|---|
| Per-call jitter | uniform 4–8 s |
| Per-batch pause | every 5 calls, 60 s |
| Cookie-stage consec-failure threshold for demote | 3 (auto-promote at 3 consec-success) |
| Whole-search-path kill threshold | 50% failure rate across 5 calls → switch pipeline to "A-only" (hot board ∩ persona) |

These live in `fetcher_factory.py` as constants — easy to tune.

### Failure detection

A response is "suspect" if any of the following hold (cheap regex over the body):

- `抱歉，未找到相关结果` present
- `count` field absent or `<= 0`
- HTML title is the search-empty title (e.g., contains `未找到`)
- Body shorter than 12 KB (Argus empty-page size)
- Body contains `argus|slardar|zijieapi|verify`

A "real result" is one with `count>=1` AND body length ≥ 14 KB.

### Observability

`tmp_3users_test/.fetcher_log.json` (gitignored): append-only list of `{ts, url, stage, status, bytes, count, suspect, latency_ms, error?}`. Keeps the last 500 entries.

## Files

### New

- `src/heated_topics_v3/fetcher_factory.py` — factory + stage ladder + pacing + failure detection
- `tmp_3users_test/harvest_cookies.py` — one-shot Playwright + DrissionPage cookie harvester
- `tmp_3users_test/.fetcher_log.json` — runtime log (gitignored)

### Modified

- `requirements.txt` (or `pyproject.toml`) — add `playwright` and `drissionpage`
- `tmp_3users_test/run_pipeline.py` — replace inline `my_fetcher` with `make_search_fetcher(...)`
- `.gitignore` — confirm `tmp_3users_test/.toutiao_cookie` and `.fetcher_log.json` covered (already covered via `tmp_3users_test/`)

### Untouched

- `src/heated_topics_v3/pipeline.py` — `run_toutiao_pipeline_v2` already accepts a `fetcher=` callable, no change required
- Any production code path

## Testing Requirements

- `harvest_cookies.py` runs cleanly, produces a cookie file with ≥5 keys.
- `make_search_fetcher()` returns a callable that satisfies `fetcher(url: str) -> str`.
- Single-keyword smoke test: stage 1 recovers at least 3 of 5 persona keywords.
- Forced-fail test: rewrite cookie file to garbage, confirm stage 2 (Playwright) takes over and recovers.
- Pacing: timestamps between consecutive fetcher calls fall in 4–8 s ± jitter.
- Log: `tmp_3users_test/.fetcher_log.json` accumulates entries with correct fields.
- Pipeline: `run_pipeline.py` for `yingjie_001.json` produces a run dir with `candidates_total > 0`.

## Acceptance Criteria

- `python tmp_3users_test/harvest_cookies.py` runs and writes a cookie file.
- `python tmp_3users_test/run_pipeline.py` for `yingjie_001.json` returns `candidates_total >= 5` and `kept_total >= 5` at least 4 out of 5 consecutive runs.
- When cookie is garbage, the pipeline still returns results (via Playwright live) within 60 s.
- No new dependency lands in `pyproject.toml` without a corresponding `requirements` lockfile update.
- The cookie file and runtime log stay git-ignored.
