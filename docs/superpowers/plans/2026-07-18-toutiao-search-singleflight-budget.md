# Toutiao Search Single-Flight And Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coalesce concurrent same-key search misses and stop the keyword-search phase within a 20-second wall-clock budget.

**Architecture:** Extend the daily search-cache module with per-key `fcntl.flock` locking and deadline-aware result states. Add one monotonic deadline around the pipeline keyword loop, forward remaining time to provider calls, and let the CLI disable legacy fetcher pacing for online runs.

**Tech Stack:** Python 3.10+, standard-library `fcntl`, `time.monotonic`, `math.ceil`, pytest threads and fake clocks.

## Global Constraints

- Search phase budget defaults to `20.0` seconds and excludes enrichment/details/reporting.
- Lock wait defaults to `2.0` seconds; timeout skips without duplicate fetch.
- macOS/Linux only; no dependency changes.
- Empty and failed results remain non-cacheable.
- Existing unrelated working-tree changes must remain intact.

---

### Task 1: Deadline-Aware File Single-Flight

**Files:**
- Modify: `src/heated_topics_v3/toutiao_search_cache.py`
- Modify: `tests/test_toutiao_search_cache.py`

**Interfaces:**
- Change `fetch_live` to `Callable[[float], list[HotItem]]`, receiving remaining seconds.
- Add keyword-only `deadline: float | None = None`, `lock_wait_seconds: float = 2.0`, and injectable `monotonic`, `sleep` callables.
- Return sources `cache`, `cache_after_wait`, `fresh`, `lock_timeout`, or `deadline_exceeded`.

- [ ] Write failing concurrent-thread, held-lock timeout, expired-deadline, leader-failure-release, and different-key tests.
- [ ] Run `uv run pytest tests/test_toutiao_search_cache.py -q` and confirm failures describe missing deadline/locking behavior.
- [ ] Implement sibling `.lock` paths, non-blocking `fcntl.flock`, 20ms polling, lock-internal cache recheck, deadline checks, and `finally` unlock/close.
- [ ] Update existing test live callables to accept the remaining-time argument.
- [ ] Run `uv run pytest tests/test_toutiao_search_cache.py -q`; expect all pass.

### Task 2: Pipeline 20-Second Search Budget

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py`
- Modify: `tests/test_toutiao_pipeline_v2.py`

**Interfaces:**
- Add keyword-only `search_phase_budget_seconds: float = 20.0` and private injectable `_monotonic=time.monotonic`.
- Forward `timeout_seconds=max(1, ceil(remaining))` to `fetch_toutiao_search_pages`.

- [ ] Write a failing fake-clock test with three keywords where the first consumes budget, asserting later keywords do not fetch and completed results survive.
- [ ] Run the focused test and confirm it fails because all keywords currently launch.
- [ ] Create one absolute deadline before the keyword loop, stop when exhausted, and pass it into `get_or_fetch_search_items`.
- [ ] Update cache-call closures to accept remaining seconds and forward bounded provider timeouts.
- [ ] Run pipeline, cache, article-info, and path tests; expect all pass.

### Task 3: Disable Online Fetcher Pacing

**Files:**
- Modify: `src/heated_topics_v3/fetcher_factory.py`
- Modify: `src/heated_topics_v3/cli.py`
- Create: `tests/test_fetcher_factory.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Add `paced: bool = True` to `SearchFetcher` and `make_search_fetcher`.
- CLI calls `make_search_fetcher(..., paced=False)`.

- [ ] Write failing tests proving default pacing still sleeps and `paced=False` never sleeps across repeated calls.
- [ ] Add a CLI assertion that online construction passes `paced=False`.
- [ ] Implement the flag without changing fallback, logging, or failure detection.
- [ ] Run `uv run pytest tests/test_fetcher_factory.py tests/test_cli.py -q`; expect all pass.

### Task 4: Documentation And Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Document the 20-second search-only budget, 2-second same-key lock, skipped-keyword tradeoff, and online pacing behavior.

- [ ] Update only the cache/anti-bot sections of README.
- [ ] Run `git diff --check` and `uv run python -m compileall -q src/heated_topics_v3`.
- [ ] Run `uv run pytest -q`; expect zero failures.
- [ ] Inspect `git status --short` and cache-related diffs without reverting unrelated changes.
