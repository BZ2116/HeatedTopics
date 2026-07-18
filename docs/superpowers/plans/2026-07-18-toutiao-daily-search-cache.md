# Toutiao Daily Search Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Share valid Toutiao keyword search results across users for one UTC+8 natural day so repeated keywords do not repeatedly call the fingerprint-sensitive Search API.

**Architecture:** Add a focused `toutiao_search_cache.py` module that owns cache keys, validation, `HotItem` serialization, and atomic persistence. The v2 pipeline wraps its existing `fetch_toutiao_search_pages` call with that module while leaving downstream enrichment and per-run raw output unchanged.

**Tech Stack:** Python 3.11+, standard-library JSON/hashlib/tempfile/pathlib, frozen dataclass contracts, pytest.

## Global Constraints

- Cache path is `cache/toutiao_search/{YYYY-MM-DD}/{cache_key}.json`.
- Cache identity includes normalized keyword, `search_pages`, `per_page`, and schema version `1`.
- Dates use UTC+8 natural days and no previous-day fallback.
- Cache entries are deployment-wide and never include user ID.
- Only non-empty parsed content-item lists are cached.
- Exceptions, empty lists, keyword placeholders, and anti-bot responses are not cached.
- Cache reads and writes must never turn a successful pipeline run into a failure.
- Article-info and article-detail calls remain live.
- Do not overwrite unrelated uncommitted changes in `README.md` or `src/heated_topics_v3/pipeline.py`.

---

## File Structure

- Create `src/heated_topics_v3/toutiao_search_cache.py`: cache key generation, payload validation, `HotItem` hydration/serialization, atomic writes, and read-through orchestration.
- Create `tests/test_toutiao_search_cache.py`: isolated cache behavior and persistence tests.
- Modify `src/heated_topics_v3/pipeline.py`: call the cache wrapper around keyword searches without changing enrichment behavior.
- Modify `tests/test_toutiao_pipeline_v2.py`: prove two users share one same-day keyword request.
- Modify `README.md`: document location, lifetime, key inputs, and non-cacheable responses.

---

### Task 1: Search Cache Module

**Files:**
- Create: `src/heated_topics_v3/toutiao_search_cache.py`
- Create: `tests/test_toutiao_search_cache.py`

**Interfaces:**
- Consumes: `HotItem`, `HeatMetrics`, and `Callable[[], list[HotItem]]`.
- Produces: `search_cache_path(cache_root, date, keyword, search_pages, per_page) -> Path` and `get_or_fetch_search_items(cache_root, date, keyword, search_pages, per_page, fetched_at, fetch_live) -> tuple[list[HotItem], str]`, where source is `"cache"` or `"fresh"`.

- [ ] **Step 1: Write failing same-day cache and key-isolation tests**

Create `tests/test_toutiao_search_cache.py` with a `_item()` helper and tests that call `get_or_fetch_search_items` twice. Assert the live callable runs once for identical inputs, runs again when `search_pages`, `per_page`, or date changes, and that whitespace-equivalent keywords share a path.

```python
def test_same_day_same_parameters_reuse_cached_items(tmp_path):
    calls = 0

    def fetch_live():
        nonlocal calls
        calls += 1
        return [_item("101")]

    first, first_source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", "AI Agent", 1, 10,
        "2026-07-18T10:00:00+08:00", fetch_live,
    )
    second, second_source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", " AI   Agent ", 1, 10,
        "2026-07-18T11:00:00+08:00", fetch_live,
    )

    assert calls == 1
    assert [item.item_id for item in second] == [first[0].item_id]
    assert (first_source, second_source) == ("fresh", "cache")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_toutiao_search_cache.py -q`

Expected: collection fails with `ModuleNotFoundError: heated_topics_v3.toutiao_search_cache`.

- [ ] **Step 3: Implement cache keys, serialization, validation, and read-through behavior**

Implement schema version `1`, normalized keyword hashing through canonical `json.dumps(..., sort_keys=True, separators=(",", ":"))`, strict payload metadata checks, complete nested `HeatMetrics` hydration, and a non-empty-item write rule.

```python
def get_or_fetch_search_items(
    cache_root: str | Path,
    date: str,
    keyword: str,
    search_pages: int,
    per_page: int,
    fetched_at: str,
    fetch_live: Callable[[], list[HotItem]],
) -> tuple[list[HotItem], str]:
    cached = load_search_items(cache_root, date, keyword, search_pages, per_page)
    if cached:
        return cached, "cache"
    items = fetch_live()
    if items:
        try:
            save_search_items(cache_root, date, keyword, search_pages, per_page, fetched_at, items)
        except OSError:
            pass
    return items, "fresh"
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/test_toutiao_search_cache.py -q`

Expected: all initial cache tests pass.

- [ ] **Step 5: Add failing invalid-data and atomic-write tests**

Add tests that verify empty results create no file, malformed JSON triggers the live callable and is replaced by valid JSON after success, and `Path.replace` is used by asserting no temporary `.toutiao_search_*.json` files remain after saving.

```python
def test_empty_live_result_is_not_cached(tmp_path):
    items, source = get_or_fetch_search_items(
        tmp_path, "2026-07-18", "不存在", 1, 10,
        "2026-07-18T10:00:00+08:00", lambda: [],
    )
    assert items == []
    assert source == "fresh"
    assert not search_cache_path(tmp_path, "2026-07-18", "不存在", 1, 10).exists()
```

- [ ] **Step 6: Run the new tests and verify RED**

Run: `uv run pytest tests/test_toutiao_search_cache.py -q`

Expected: malformed-entry repair or temporary-file cleanup test fails until atomic persistence and tolerant loading are complete.

- [ ] **Step 7: Complete tolerant reads and atomic writes**

Use `tempfile.mkstemp(dir=path.parent, prefix=".toutiao_search_", suffix=".json")`, write UTF-8 JSON, and call `Path(tmp_name).replace(path)`. Catch `JSONDecodeError`, `OSError`, `KeyError`, `TypeError`, and `ValueError` during reads and return `None`; unlink the temporary file on failed writes before re-raising.

- [ ] **Step 8: Run the module tests**

Run: `uv run pytest tests/test_toutiao_search_cache.py -q`

Expected: all tests pass.

- [ ] **Step 9: Commit the module**

```bash
git add src/heated_topics_v3/toutiao_search_cache.py tests/test_toutiao_search_cache.py
git commit -m "feat(toutiao): cache daily keyword search results"
```

---

### Task 2: Pipeline Integration And Cross-User Sharing

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py:337-370`
- Modify: `tests/test_toutiao_pipeline_v2.py`

**Interfaces:**
- Consumes: `get_or_fetch_search_items(...) -> tuple[list[HotItem], str]` from Task 1 and existing `fetch_toutiao_search_pages(...)`.
- Produces: unchanged `run_toutiao_pipeline_v2(...) -> ToutiaoV2Result` behavior with shared search caching under `hot_board_cache_root / "toutiao_search"`.

- [ ] **Step 1: Write a failing cross-user pipeline test**

Create two profiles with the same single `core_keywords` value and different `user_id` values. Use an empty hot board so search executes, count only URLs containing `so.toutiao.com/search`, run both profiles with the same cache root, and assert one search call total. Supply explicit article-info and detail fetchers so those live calls do not affect the assertion.

```python
def test_pipeline_shares_daily_search_cache_across_users(tmp_path):
    search_calls = 0

    def search_fetcher(url, _timeout):
        nonlocal search_calls
        if "hot-event/hot-board" in url:
            return json.dumps({"status": "success", "data": []})
        if "so.toutiao.com/search" in url:
            search_calls += 1
            return _search_response("901", "共享关键词文章")
        raise AssertionError(url)

    run_for(_profile("user_a", ["共享关键词"]), search_fetcher)
    run_for(_profile("user_b", ["共享关键词"]), search_fetcher)

    assert search_calls == 1
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/test_toutiao_pipeline_v2.py::test_pipeline_shares_daily_search_cache_across_users -q`

Expected: FAIL with `assert 2 == 1`.

- [ ] **Step 3: Wrap the existing search call with the cache**

Import `get_or_fetch_search_items`. Inside the existing keyword loop, bind effective parameters once and use a zero-argument closure for the live request.

```python
search_pages = path_filters.search_pages or 1
results, _search_source = get_or_fetch_search_items(
    hot_board_cache_root,
    date,
    keyword,
    search_pages,
    path_filters.per_page,
    fetched_at,
    lambda: fetch_toutiao_search_pages(
        keyword,
        fetched_at=fetched_at,
        max_pages=search_pages,
        per_page=path_filters.per_page,
        fetcher=fetcher,
    ),
)
```

Keep the existing exception-to-empty-list behavior around the wrapper. Do not change article-info enrichment, quota callbacks, candidate filtering, or raw output.

- [ ] **Step 4: Run focused pipeline and cache tests**

Run: `uv run pytest tests/test_toutiao_pipeline_v2.py::test_pipeline_shares_daily_search_cache_across_users tests/test_toutiao_search_cache.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Run all Toutiao pipeline tests**

Run: `uv run pytest tests/test_toutiao_pipeline_v2.py tests/test_toutiao_article_info.py tests/test_toutiao_paths.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit only cache integration hunks**

Because `pipeline.py` contains pre-existing user changes, inspect `git diff`, stage only the cache import/integration hunks, stage the new test, and verify the staged diff before committing.

```bash
git diff -- src/heated_topics_v3/pipeline.py tests/test_toutiao_pipeline_v2.py
git add -p src/heated_topics_v3/pipeline.py
git add tests/test_toutiao_pipeline_v2.py
git diff --cached --check
git commit -m "feat(toutiao): share search cache across users"
```

---

### Task 3: Documentation And Full Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: implemented cache location and behavior from Tasks 1-2.
- Produces: user-facing operational documentation; no code API.

- [ ] **Step 1: Update README cache documentation**

Add `cache/toutiao_search/{date}/{cache_key}.json` to the pipeline/cache description. State that the UTC+8 date, normalized keyword, `search_pages`, `per_page`, and schema version form the cache identity; valid non-empty parsed results are shared across users; empty/failed/anti-bot results are not cached; and article-info/detail requests remain live.

- [ ] **Step 2: Check documentation consistency**

Run:

```bash
rg -n "toutiao_search|自然日|search_pages|per_page|article.info" README.md docs/superpowers/specs/2026-07-18-toutiao-daily-search-cache-design.md
git diff --check
```

Expected: README contains every required cache rule and `git diff --check` prints nothing.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -q`

Expected: all tests pass with no collection errors.

- [ ] **Step 4: Review final scope**

Run:

```bash
git status --short
git diff -- src/heated_topics_v3/toutiao_search_cache.py src/heated_topics_v3/pipeline.py tests/test_toutiao_search_cache.py tests/test_toutiao_pipeline_v2.py README.md
```

Expected: only cache-related hunks from this implementation are attributed to this task; pre-existing user edits remain intact.

- [ ] **Step 5: Commit only README cache hunks**

Because README already contains pre-existing changes, stage only the new cache documentation hunk and inspect it before committing.

```bash
git add -p README.md
git diff --cached --check
git commit -m "docs(toutiao): document daily search cache"
```
