# Cached News Providers Implementation Report

**Date:** 2026-07-23
**Branch:** `feature/cached-news-providers`
**Base commit:** `8da8d299b95dcc3f859168194c81f978f388d57a`
**Task:** Task 10 — Real Anonymous Smoke Tests and Recorded Evidence

## 0. Verdict

**ready-for-review with caveats.** The anonymous daily collection and
recommendation workflow does not yet produce eligible news records against
the live public endpoints; the only persisted artefacts are raw responses and
normalized payloads. All 267 mocked tests pass. Two implementation defects
were reproduced under real network calls and are documented below as open
issues. They do not block the V1 Toutiao/Juejin regression set.

## 1. Smoke environment

| Item | Value |
| --- | --- |
| Shell | bash (Git Bash on Windows 11) |
| OS | Windows 11 Home 10.0.26200 |
| Python | managed by `uv` |
| `$SMOKE_ROOT` | `C:\Users\BruceZhao\AppData\Local\Temp\heatedtopics-news-smoke-oWpZhh` (also accessible as `/tmp/heatedtopics-news-smoke-oWpZhh` in Git Bash) |
| Smoke root in git | NOT committed (lives outside the worktree) |
| Network path | direct egress to `top.news.sina.com.cn`, `cache.thepaper.cn`, `gw.m.163.com` |
| Auth headers in any HTTP request | none — `User-Agent: heatedtopics-v1/0.1 (+anonymous-public-data)` only |
| Tooling | `uv run heated-topics collect-news` / `generate-news` / `tools/validate_news_smoke.py` |

## 2. Daily collection (Step 1)

Two `uv run heated-topics collect-news --data-root "$SMOKE_ROOT"` invocations
were issued. Both failed at the per-platform stage with the same exceptions.

| Platform | Run | status | items | raw | normalized | eligible | rejected | error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sina_news | #1 | failed | 0 | yes (50 rows, JSONP body 26 023 chars) | yes (50 rows) | no | no | `AttributeError: 'tuple' object has no attribute 'raw_payload'` |
| sina_news | #2 | failed | 0 | reused #1 (no re-fetch) | reused #1 | no | no | identical error |
| thepaper | #1 | failed | 0 | no | no | no | no | `ValueError: empty official hot board` |
| thepaper | #2 | failed | 0 | no | no | no | no | identical error |
| netease_news | #1 | failed | 0 | yes (20-row `code 0` JSON, 20 707 chars) | no | no | no | `AttributeError: 'NeteaseNewsProvider' object has no attribute 'absolute_floors'` |
| netease_news | #2 | failed | 0 | reused #1 (no re-fetch) | no | no | no | identical error |

`collection_status.json` (last write wins, idempotent across the two runs):

```json
[
  {"platform": "sina_news", "status": "failed", "item_count": 0, "error": "AttributeError"},
  {"platform": "thepaper",  "status": "failed", "item_count": 0, "error": "ValueError"},
  {"platform": "netease_news", "status": "failed", "item_count": 0, "error": "AttributeError"}
]
```

`repository.publish_active_snapshot` was correctly skipped for the three
failed platforms (verified by absence of `daily_hot_lists/2026-07-23/active/`
on disk).

### 2.1 Endpoint status

| Platform | Endpoint | Status | Notes |
| --- | --- | --- | --- |
| sina_news | `https://top.news.sina.com.cn/ws/GetTopDataList.php?…&top_show_num=50` | `success` (200, 26 023-char JSONP `var data = {...};` envelope) | schema unchanged from spec §18 |
| thepaper | `https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar` | `error` (`ValueError: empty official hot board`) | provider raises before parsing — see §3 issue B |
| netease_news | `https://gw.m.163.com/nc-main/api/v1/hqc/no-repeat-hot-list` | `success` (200, `code 0` JSON, 20 707 chars) | schema unchanged from spec §18 |

Both successful endpoints returned the expected shape; no schema drift
detected in the bodies that were captured.

## 3. Implementation defects surfaced by the smoke test

These were reproduced against the unmodified `feature/cached-news-providers`
HEAD (`8da8d29`). They are not regressions of V4 V1 and do not affect the
267-test regression suite, which uses in-memory provider doubles.

**Issue A — `SinaNewsProvider.enrich_metrics` signature mismatch.**
Location: `src/heated_topics_v3/providers/sina_news.py:79`. The method
declares `def enrich_metrics(self, item: HotItem, collected_at: str) -> HotItem`
but `_collect_news_platform` calls it as
`provider.enrich_metrics(capture.items, collected_at)` and then indexes the
first row (`item.raw_payload`). Under real data the parameter is a tuple of
50 `HotItem` and the attribute lookup throws `AttributeError`. Mock
providers in `tests/test_news_collection.py` declare the correct
`Sequence[HotItem] -> tuple[HotItem, ...]` signature, which is also the
`NewsProvider` protocol contract at
`src/heated_topics_v3/providers/common.py:40`. Net effect: sina never reaches
detail fetching, eligible/rejected, or search.

**Issue B — `NeteaseNewsProvider` and `ThePaperProvider` lack `absolute_floors`.**
`dynamic_floors` (called from `_collect_news_platform` at
`src/heated_topics_v3/collection.py:316`) requires
`provider.absolute_floors: Mapping[str, float]`. The `NewsProvider` protocol
(`src/heated_topics_v3/providers/common.py:26`) declares the attribute, but
neither the netease nor the thepaper provider class sets it. The sina
provider is also missing the attribute, but its crash is masked by Issue A.
On the thepaper path, `collect_hot_list` itself raises `ValueError: empty
official hot board` before the attribute is consulted, so the failure mode
is benign for that platform today but the underlying contract gap remains.
Net effect: even after Issue A is fixed, the netease path still throws
`AttributeError` at `dynamic_floors`; the thepaper path additionally needs
the empty-board guard to be re-examined.

**No other provider defects were reproduced.** The raw-to-normalized handoff,
JSONP envelope parsing, netease envelope parsing, and per-item
`raw_payload` storage all worked for the responses that were captured.

## 4. Generate-news runs (Step 2)

Profiles created (committed):

- `config/profiles/news_smoke_common.json` — `primary_keyword: "的"`, track
  `综合新闻 / 热榜`.
- `config/profiles/news_smoke_ai.json` — `primary_keyword: "人工智能"`, track
  `人工智能 / 产业新闻`.

All four `uv run heated-topics generate-news …` invocations returned
`{"status":"failed","command":"generate-news","error":"AttributeError"}`
and produced no `news_user_results/<user_id>/<date>/result.json` files.
The exception is the same one raised inside the daily collection — the
recommendation path calls `collect_news_daily` and then reuses its eligible
snapshots, so any failure there propagates.

| Run | Profile | Expected status | Observed status | Search calls |
| --- | --- | --- | --- | --- |
| common #1 | `news_smoke_common` | `generated` / `no_result` | `failed` (`AttributeError`) | not exercised |
| common #2 | `news_smoke_common` | `existing`, no new search | `failed` (`AttributeError`) | not exercised |
| ai #1 | `news_smoke_ai` | `generated` / `no_result` | `failed` (`AttributeError`) | not exercised |
| ai #2 | `news_smoke_ai` | `existing`, no new search | `failed` (`AttributeError`) | not exercised |

The 5-vs-5 cached-matches branch and the bounded-search branch could not
be exercised end-to-end. Cache reuse is still observable at the daily
level: the second `collect-news` call did not re-hit the sina or netease
endpoints (raw files were reused from the first call's timestamp).

## 5. Validator (Step 3 & 4)

```
$ uv run python tools/validate_news_smoke.py /tmp/heatedtopics-news-smoke-oWpZhh
{"status": "success", "violations": []}
```

- Zero credential-shaped strings (no `authorization`, `cookie`, `api_key`,
  `token`, or `secret` values in any persisted JSON).
- No `result.json` files were written by the failed smoke runs, so the
  `content` / `evidence` / `limit` / `order` checks had no data to evaluate.
- No eligible/rejected overlap (both directories are empty).

`tools/validate_news_smoke.py` is the exact code from
`docs/superpowers/plans/2026-07-23-cached-news-providers.md` Task 10
Step 3.

## 6. Final verification (Step 5)

| Command | Result |
| --- | --- |
| `uv run pytest -q` | `267 passed in 5.19s` |
| `uv run python -m compileall -q src tests` | exit 0 |
| `git diff --check` | exit 0 |
| `git status --short` (after Step 6 commit) | clean |

No tests were modified. The only new test in this worktree would be
`tests/test_news_smoke_validator.py`; per the brief I did not add it
because the spec already provides the script and no separate test
contract was requested. The validator is a stand-alone script and is
intentionally not exercised by the regression suite.

## 7. Files added in this commit

- `config/profiles/news_smoke_common.json`
- `config/profiles/news_smoke_ai.json`
- `tools/validate_news_smoke.py`
- `docs/specs/cached-news-providers-implementation-report.md` (this file)

`$SMOKE_ROOT` is intentionally outside the worktree and is not committed.
`daily_hot_lists/2026-07-23/raw/sina_news.txt` and
`daily_hot_lists/2026-07-23/raw/netease_news.json` contain only the public
top-list envelopes (titles, ranks, metric numbers, image URLs) — no full
article bodies — but they still live outside the worktree, in `$SMOKE_ROOT`,
and are not staged for commit.

## 8. Open issues for follow-up agents

1. Align `SinaNewsProvider.enrich_metrics` (and any other provider still on
   the single-item signature) with the `NewsProvider` protocol.
2. Declare `absolute_floors` on `SinaNewsProvider`, `NeteaseNewsProvider`,
   and `ThePaperProvider` so `dynamic_floors` can run; alternatively change
   `dynamic_floors` to fall back to an empty mapping when the provider does
   not declare one.
3. Re-investigate `ThePaperProvider.collect_hot_list` to understand why
   `capture.items` is empty against the real `cache.thepaper.cn/.../
   rightSidebar` endpoint; this is masked by the `ValueError` raised in
   `_collect_news_platform` before the issue is observable.
4. After items 1–3 are fixed, re-run this smoke test in a clean
   `$SMOKE_ROOT` so `eligible/`, `rejected/`, and `result.json` files are
   actually produced; the validator will then exercise its full contract
   surface.

## 9. Spec compliance self-check

1. Three daily boards are anonymous and fetched once per run — partial.
   Sina and netease fetched once each; thepaper did not yield items.
   Reuse on the second run was confirmed by file timestamps.
2. Raw / normalized / eligible / rejected / status files per platform —
   partial. Sina produced raw + normalized; the others produced status only.
3. ≥5 cached matches on the common profile skip search — not exercised
   (no eligible snapshot).
4. <5 cached matches trigger bounded search — not exercised.
5. `tools/validate_news_smoke.py` returns zero violations on the actual
   smoke artefacts — **yes**.
