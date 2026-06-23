# Detail Collection, Cache, and Session Safety Design

Date: 2026-06-23

## Goals

This design records two changes for the hot topic pipeline:

1. Keep full DailyHot topic discovery, but limit expensive detail collection to selected platforms.
2. Add a 7-day cache so repeated weekly runs reuse recent route and detail results.

It also records the session keepalive and platform-safety policy for Weibo and Xiaohongshu.

## Detail Collection Scope

DailyHot API remains the broad discovery layer. All configured DailyHot routes should continue to be fetched so the report still sees cross-platform topics.

Only these platforms should enter the expensive detail collection layer:

- `weibo`
- `baidu`
- `xiaohongshu`
- `bilibili`
- `juejin`

All other platforms remain in the report as DailyHot metadata only. They should keep the existing topic layout, source rows, rank, heat value, URL, and DailyHot summary fields, but they should not trigger browser detail collection, search expansion, or extra API calls.

## Detail Flow

The pipeline should use two separate platform sets:

- `DISCOVERY_ROUTES`: all DailyHot routes used for topic discovery.
- `DETAIL_ENABLED_PLATFORMS`: the five platforms listed above.

The detail collector should decide per topic:

1. If a topic has a source from `DETAIL_ENABLED_PLATFORMS`, run the matching provider.
2. If a topic only has non-detail platforms, create lightweight metadata evidence from DailyHot records.
3. If Weibo or Xiaohongshu login state is missing, skip only that platform's detail provider and continue with the rest.

## Platform Strategy

`baidu`

- Use Baidu search result detail collection.
- If direct HTTP search hits Baidu security verification, fall back to Playwright browser search.

`weibo`

- Use saved browser login state.
- Collect search result cards and discussion text.
- If login, captcha, slider, risk-control, or unusual verification appears, stop Weibo collection for that run.

`xiaohongshu`

- Use saved browser login state.
- Collect search result cards and note text.
- If login, captcha, slider, risk-control, or unusual verification appears, stop Xiaohongshu collection for that run.

`bilibili`

- Initially use DailyHot video metadata: title, description, author, heat, and URL.
- Deeper page fetch can be added later if needed.

`juejin`

- Add a detail provider for article metadata and snippets: title, author, publish time, summary/body snippet, URL.

## Cache Design

Use local JSON cache under:

```text
data/cache/
  hot_routes/
  detail_evidence/
  cache_index.json
```

### DailyHot Route Cache

Cache key:

```text
dailyhot:{route}:{window}:{date_bucket}
```

Examples:

```text
dailyhot:weibo:today:2026-06-23
dailyhot:baidu:last_7_days:2026-W26
```

If a route cache entry is younger than 7 days, reuse it instead of calling DailyHot again.

### Detail Evidence Cache

Cache key:

```text
detail:{platform}:{normalized_topic_key}
```

Each entry stores:

- `DetailEvidence`
- `fetched_at`
- `platform`
- `topic_key`
- `source_method`
- `fetch_status`
- `result_urls`
- compact raw payload

If an entry is younger than 7 days, reuse it instead of calling the platform provider again.

### Refresh Control

Add:

```powershell
uv run python -m src.core_pipeline.run collect-recent-details --window today --refresh
```

`--refresh` bypasses cache reads and writes fresh results after collection.

Optional debug override:

```powershell
uv run python -m src.core_pipeline.run collect-recent-details --window today --detail-platforms baidu,weibo,xiaohongshu
```

## Session Keepalive

Weibo and Xiaohongshu should use manually created Playwright storage state files:

```text
data/browser_state/weibo.json
data/browser_state/xiaohongshu.json
```

Keepalive should be conservative:

1. Before a weekly run, check whether each storage state exists and has cookies.
2. Optionally open the platform home/search page once with saved state.
3. If the page is normal, mark the session `ok`.
4. If redirected to login, mark `login_required`.
5. If captcha, slider, risk-control, or security verification appears, mark the platform blocked for this run and require manual attention.

Do not attempt to bypass captcha, slider verification, account risk checks, or platform access controls.

## Platform Safety Policy

The project should reduce account risk by behaving like a low-frequency, user-authorized reader:

- Run weekly by default.
- Use a small detail topic limit per platform per run.
- Reuse 7-day cache aggressively.
- Add delays and jitter between browser page visits.
- Avoid concurrent browser scraping for the same logged-in account.
- Stop a platform immediately when guard pages appear.
- Keep screenshots or raw snapshots for debugging only when needed.
- Prefer official APIs or public RSS/feeds when available.
- Do not use proxy rotation, fingerprint spoofing, captcha bypassing, or automated login solving.

Recommended first limits:

```text
weibo: max 20 topics per weekly run
xiaohongshu: max 20 topics per weekly run
baidu: max 80 topics per weekly run
bilibili: metadata only
juejin: max 30 topics per weekly run
```

These limits can be raised after observing stability.

## Implementation Order

1. Add `DETAIL_ENABLED_PLATFORMS`.
2. Update topic detail selection to skip expensive providers for non-detail platforms.
3. Add metadata evidence for non-detail platforms.
4. Add cache store with 7-day TTL.
5. Add route-level DailyHot cache.
6. Add detail evidence cache.
7. Add `--refresh`.
8. Add optional `--detail-platforms`.
9. Add conservative session keepalive checks.
10. Add per-platform detail limits and delay/jitter.
11. Add tests for cache hit, cache expiry, detail platform filtering, partial login state, and guard-page handling.
