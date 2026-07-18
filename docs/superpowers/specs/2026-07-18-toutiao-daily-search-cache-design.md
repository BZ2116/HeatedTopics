# Toutiao Daily Search Cache Design

## Purpose

Reduce repeated calls to Toutiao's fingerprint-sensitive search endpoint by sharing valid keyword search results across users for one UTC+8 natural day.

The cache covers keyword search results only. Article-info and article-detail requests remain live so heat metrics and content can still refresh independently.

## Scope

- Cache parsed results returned by `fetch_toutiao_search_pages`.
- Share cache entries across all users of the same deployment.
- Partition entries by UTC+8 calendar date.
- Preserve existing per-run raw search output.
- Do not change quota accounting, hot-board caching, candidate filtering, ranking, or detail fetching.

## Storage Contract

Cache files live at:

```text
cache/toutiao_search/{YYYY-MM-DD}/{cache_key}.json
```

`cache_key` is a SHA-256 digest derived from a canonical JSON object containing:

```json
{
  "keyword": "normalized keyword",
  "search_pages": 1,
  "per_page": 10,
  "schema_version": 1
}
```

Keyword normalization trims leading and trailing whitespace and collapses internal whitespace. It does not lowercase the keyword because Chinese text is unaffected and English keyword case may carry user intent.

Each cache payload contains:

```json
{
  "schema_version": 1,
  "date": "2026-07-18",
  "keyword": "AI Agent",
  "search_pages": 1,
  "per_page": 10,
  "fetched_at": "2026-07-18T10:00:00+08:00",
  "items": []
}
```

Items use the existing `HotItem` serialization contract. Cache writes use a temporary sibling file followed by atomic replacement.

## Read And Write Rules

For every keyword that reaches the search path:

1. Resolve today's UTC+8 cache path from the normalized keyword and search parameters.
2. If a valid cache entry exists, deserialize and return its items without calling Toutiao Search API.
3. If the entry is missing, malformed, has the wrong schema/date/parameters, or cannot deserialize, ignore it and fetch live.
4. Write a cache entry only when the live request produces at least one real content item.
5. Do not cache exceptions, empty lists, keyword placeholder items, suspected anti-bot responses, or partially written data.

An invalid cache entry is left untouched during the failed read. A successful live response replaces it atomically. This avoids destructive cleanup and lets the next successful fetch repair the entry.

## Pipeline Integration

Add a dedicated `toutiao_search_cache.py` module. Its public operation accepts the cache root, date, keyword, search parameters, fetched timestamp, and a callable that performs the live search.

`run_toutiao_pipeline_v2` passes `hot_board_cache_root` as the common cache root and wraps its existing `fetch_toutiao_search_pages` call. The existing `raw_search_by_keyword` and downstream enrichment structures remain unchanged, so reports and run artifacts keep their current shape.

The cache is deployment-wide rather than user-specific. Two users searching the same normalized keyword with the same pagination settings on the same UTC+8 date share one Search API call.

## Failure Behavior

- Cache read failure: log no secret data, fetch live, and continue.
- Live search failure: preserve the pipeline's existing empty-result fallback and do not cache it.
- Cache write failure: return the successful live results and continue; caching must not make a successful run fail.
- Concurrent writers: atomic replacement prevents partial JSON. Duplicate simultaneous live requests are acceptable in this version; cross-process locking is out of scope.

## Testing

Tests must prove:

1. A second request for the same keyword and parameters on the same date uses the cache.
2. Different users share the same cache entry through the pipeline.
3. Different `search_pages` or `per_page` values do not share entries.
4. The next UTC+8 date does not reuse the previous day's entry.
5. Empty or failed live results are not cached.
6. A malformed cache entry triggers a live request and is repaired after success.
7. Cache writes are atomic.
8. Existing pipeline and full test suites remain green.

## Documentation

Update `README.md` to document:

- the shared daily cache location;
- the UTC+8 natural-day lifetime;
- the cache-key inputs;
- the rule that empty or anti-bot responses are never cached;
- the fact that article-info and article-detail calls remain live.

## Acceptance Criteria

- Two same-day pipeline runs with the same keyword and search settings issue one Toutiao Search API request in total.
- A second user receives the same cached search items without another Search API request.
- Empty or malformed responses never become reusable cache entries.
- The next UTC+8 day performs a fresh search.
- `uv run pytest -q` passes.
