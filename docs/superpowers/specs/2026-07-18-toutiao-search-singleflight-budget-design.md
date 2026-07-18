# Toutiao Search Single-Flight And Budget Design

## Purpose

Keep the keyword-search phase within a 20-second wall-clock budget while preventing concurrent users from issuing duplicate Toutiao Search API requests for the same daily cache key.

The 20-second budget covers keyword cache lookup, lock waiting, and live calls to `fetch_toutiao_search_pages`. It does not cover hot-board loading, `article_info`, article-detail fetching, report rendering, or output writing.

## Constraints

- Search-phase wall-clock budget defaults to `20.0` seconds.
- Per-key single-flight lock wait defaults to `2.0` seconds.
- Locking supports macOS and Linux through standard-library `fcntl.flock`.
- No dependency changes are required.
- Response time has priority over completing every keyword.
- A lock timeout skips that keyword; it must not start a duplicate live request.
- Existing valid daily cache entries remain immediately reusable.
- Empty, failed, placeholder, and anti-bot search responses remain non-cacheable.

## Single-Flight Contract

Each daily search cache file has a sibling lock file:

```text
cache/toutiao_search/{YYYY-MM-DD}/{cache_key}.json
cache/toutiao_search/{YYYY-MM-DD}/{cache_key}.lock
```

For each keyword:

1. Read the cache without locking.
2. On a miss, try to acquire an exclusive non-blocking `flock`, polling until the earlier of the 2-second lock deadline or the search-phase deadline.
3. After acquiring the lock, read the cache again.
4. If the second read hits, return the cached items without a live request.
5. If it still misses, run the supplied live fetch with the remaining search-phase budget.
6. Save only valid non-empty content items, then release the lock in `finally`.
7. If lock acquisition times out, return an empty skipped result and do not call the live fetch.

Lock files remain on disk. The operating system releases `flock` automatically when a process exits; deleting lock files is avoided because unlinking can race with another process opening the same path.

## Time Budget Contract

`run_toutiao_pipeline_v2` starts one monotonic deadline immediately before iterating `keyword_phrases`:

```text
deadline = monotonic() + search_phase_budget_seconds
```

Before every keyword, the pipeline computes the remaining time. If no time remains, it records an empty result for the current and remaining keywords and exits the search loop.

The cache operation receives the shared absolute deadline. The live fetch callable receives the remaining timeout in seconds, and the pipeline forwards a bounded integer timeout to `fetch_toutiao_search_pages`:

```text
timeout_seconds = max(1, ceil(remaining_seconds))
```

The fetcher and provider must not receive a timeout greater than the remaining search-phase budget. Work already completed before the deadline is preserved and continues into enrichment and ranking.

The budget is best-effort at the Python boundary: a transport or browser implementation that ignores its timeout may overrun. Existing supported fetchers honor their timeout argument; tests use deterministic fake clocks and fetchers.

## Result Semantics

The cache operation returns one of:

- `cache`: initial cache hit.
- `cache_after_wait`: another worker populated the cache while this request waited.
- `fresh`: this request acquired the lock and completed the live fetch.
- `lock_timeout`: the lock was not acquired within the allowed wait.
- `deadline_exceeded`: no search budget remained before a live fetch could start.

The pipeline keeps its existing `raw_search_by_keyword` shape. Skipped or deadline-exceeded keywords map to empty lists, so downstream candidate building requires no contract change.

## Fetcher Pacing

The 60-second batch rest cannot run inside a 20-second online search budget. Search calls made through the budgeted pipeline must bypass `SearchFetcher`'s batch rest and 4–8 second inter-call sleep.

Add an optional `paced` setting to `make_search_fetcher` / `SearchFetcher`, defaulting to the current behavior for compatibility. The CLI creates the online pipeline fetcher with `paced=False`; diagnostic or offline scripts keep `paced=True` unless explicitly changed.

Disabling client-side pacing does not disable stage fallback, failure detection, logging, cookies, or request timeouts. The daily cache and single-flight lock remain the primary controls preventing request amplification.

## Failure Behavior

- Initial cache read failure: continue to lock acquisition and live fetch.
- Lock timeout: return immediately with no live request.
- Leader live fetch failure: release the lock; a later request may retry.
- Cache write failure: return successful live items and release the lock.
- Search deadline reached: stop launching additional keyword searches and preserve completed results.
- Unsupported platform without `fcntl`: raise a clear runtime error during lock creation; Windows support is out of scope for this version.

## Testing

Tests must prove:

1. Two threads requesting the same missing key concurrently execute one live fetch.
2. The waiting request returns `cache_after_wait` after the leader writes the cache.
3. A held lock exceeding 2 seconds returns `lock_timeout` without invoking live fetch.
4. A failed leader releases the lock so a later request can retry.
5. No remaining deadline returns `deadline_exceeded` without invoking live fetch.
6. Different cache keys do not block each other.
7. Pipeline keyword iteration stops at the 20-second budget and preserves completed results.
8. Live fetch timeout never exceeds the remaining budget.
9. CLI online search disables fetcher pacing while pacing remains enabled by default elsewhere.
10. Existing cache, pipeline, fetcher, and complete project tests remain green.

## Documentation

Update `README.md` to state:

- the keyword-search phase has a default 20-second budget;
- the budget excludes hot-board, enrichment, details, reporting, and output;
- concurrent identical cache misses use a 2-second single-flight lock;
- lock timeout or exhausted budget may reduce the number of searched keywords;
- online CLI search disables fetcher pacing to meet the latency budget.

## Acceptance Criteria

- A deterministic pipeline test completes the keyword-search phase at or before its 20-second fake-clock deadline.
- Concurrent same-key cache misses produce exactly one live Search API call.
- A request that cannot acquire the lock within 2 seconds does not issue a duplicate call.
- Completed keyword results remain available when later keywords are skipped by the deadline.
- `uv run pytest -q` passes.
