# Toutiao and Juejin V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver and smoke-test a complete two-platform recommendation workflow using Toutiao official/search data and Juejin official hot-rank data.

**Architecture:** Extend the existing reviewed providers instead of rebuilding them. Normalize real Toutiao `dom` search cards, join them to the daily board for Level 1 evidence, keep unmatched results as Level 3, then orchestrate collection, deterministic matching, reporting, caching, and CLI output through the existing contracts and filesystem repository.

**Tech Stack:** Python 3.10+, `httpx`, standard-library HTML/JSON parsing, dataclasses, pytest, Markdown/JSON/TXT files.

## Global Constraints

- V1 supports only `toutiao` and `juejin`.
- Toutiao official board records are Level 1 and preserve rank and `HotValue`.
- Toutiao keyword search uses exactly the saved `primary_keyword`.
- The search response top-level `count` is never heat.
- Search results are cross-checked by `group_id`, canonical URL, then normalized title.
- Overlap is Level 1; non-overlap remains visible as Level 3 with the exact notice `来自头条关键词搜索，未发现官方热榜证据`.
- Juejin official hot-rank matches are Level 1.
- User matching is Unicode-normalized substring matching over title, summary, and detail; no LLM.
- Preserve platform order `toutiao`, then `juejin`; do not rank across platforms or deduplicate across platforms.
- Store raw, normalized, detail, Markdown, JSON, and minimal TXT artifacts in the approved layout.
- Never invent missing text or serialize secrets.
- Same user/business-day generation is cached and atomically published.

---

### Task 1: Parse Real Toutiao Search DOM

**Files:**
- Modify: `src/heated_topics_v3/providers/toutiao.py`
- Modify: `tests/providers/test_toutiao.py`
- Replace: `tests/fixtures/toutiao_search.json`

**Interfaces:**
- Consumes: existing `ToutiaoProvider`, `ProviderCapture`, `HotItem`.
- Produces: `parse_search` support for current `{count, dom, ...}` responses and stable `group_id` in raw payload.

- [ ] Capture and sanitize a current search response fixture containing at least two real result cards.
- [ ] Write failing tests proving `dom` cards yield title, canonical content URL, group ID, summary, source, and publication time where present; assert top-level `count` does not populate heat.
- [ ] Run `uv run pytest tests/providers/test_toutiao.py -q` and confirm failure.
- [ ] Implement a focused HTML parser for result cards and retain the existing legacy `data` parser only as compatibility fallback.
- [ ] Assign `metric_name="search_rank"` with no claim of official heat; do not invent reads/comments.
- [ ] Run focused tests and `uv run pytest -q`; commit `fix: parse current toutiao search results`.

### Task 2: Match, Cross-Validate, and Classify V1 Results

**Files:**
- Create: `src/heated_topics_v3/matching.py`
- Create: `tests/test_matching.py`

**Interfaces:**
- Consumes: `UserProfile`, board/search `HotItem`, and `ItemDetail`.
- Produces: `matches_primary_keyword(...)`, `merge_toutiao_results(board, search)`, and `build_v1_recommendations(...)`.

- [ ] Write failing tests for Unicode-normalized keyword matching across title/summary/detail.
- [ ] Write failing overlap tests for group ID, canonical URL, and normalized-title fallback.
- [ ] Assert overlap inherits official rank/`HotValue` and becomes Level 1; non-overlap becomes Level 3 with the exact notice.
- [ ] Assert Juejin official matches are Level 1 and platform/source order is preserved.
- [ ] Implement deterministic matching and classification without cross-platform deduplication.
- [ ] Run `uv run pytest tests/test_matching.py -q` and full suite; commit `feat: classify v1 personalized topics`.

### Task 3: Orchestrate Two-Platform Collection

**Files:**
- Create: `src/heated_topics_v3/collection.py`
- Create: `tests/test_collection.py`

**Interfaces:**
- Consumes: `ToutiaoProvider`, `JuejinProvider`, and `FileRepository`.
- Produces: `collect_v1_daily(now, repository, providers) -> DailySnapshot`.

- [ ] Write failing fake-provider tests proving both raw responses are saved, normalized board files are written, and each normalized item receives a detail TXT.
- [ ] Assert one platform failure is isolated and represented in `collection_status.json`.
- [ ] Implement small independent detail pools with at most three workers per platform and immediate per-item persistence.
- [ ] Reuse existing saved details on a repeated collection run.
- [ ] Run focused and full tests; commit `feat: collect toutiao and juejin daily data`.

### Task 4: Generate and Render Cached User Results

**Files:**
- Create: `src/heated_topics_v3/reporting.py`
- Create: `src/heated_topics_v3/recommendation.py`
- Create: `tests/test_reporting.py`
- Create: `tests/test_recommendation.py`

**Interfaces:**
- Consumes: profile/clock/storage/provider/matching services.
- Produces: `generate_v1_user_result(...) -> RecommendationBundle`, `render_markdown`, `serialize_bundle`, and `render_topic_txt`.

- [ ] Write failing output tests for fixed platform order, Level 1/3 separation, exact unverified notice, rich JSON, and minimal TXT fields.
- [ ] Write failing generation tests for one exact Toutiao keyword search, board overlap, Juejin matches, atomic output, and same-day `existing` reuse.
- [ ] Implement report renderers and generation orchestration.
- [ ] Ensure search failure still returns official-board matches.
- [ ] Run focused and full tests; commit `feat: generate v1 recommendation artifacts`.

### Task 5: Add CLI and Run Real Smoke Test

**Files:**
- Create: `src/heated_topics_v3/cli.py`
- Modify: `src/heated_topics_v3/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Create: `tests/test_cli.py`
- Create: `docs/specs/toutiao-juejin-v1-implementation-report.md`

**Interfaces:**
- Produces: `heated-topics collect-v1 --data-root <path>` and `heated-topics generate-v1 --data-root <path> --profile <json>`.

- [ ] Write failing CLI tests for command arguments, JSON status output, and failure exit codes.
- [ ] Implement CLI wiring and public exports; document `.env`-free anonymous V1 operation.
- [ ] Run `uv run pytest -q` and confirm all tests pass.
- [ ] Run a real `collect-v1` against anonymous Toutiao and Juejin endpoints into `data/`.
- [ ] Create one realistic profile JSON and run `generate-v1` twice; first returns `generated` or `no_result`, second returns `existing`.
- [ ] Inspect real raw/normalized/detail/Markdown/JSON/TXT artifacts and scan `data/` for secret leakage.
- [ ] Record actual counts, elapsed time, detail success/fallback counts, and sample result paths in the implementation report.
- [ ] Commit `feat: deliver toutiao and juejin v1 workflow`.

## Final Verification

- [ ] Run `uv run pytest -q` with pristine passing output.
- [ ] Confirm real Toutiao and Juejin raw/normalized/detail artifacts exist.
- [ ] Confirm current Toutiao search `dom` produces records.
- [ ] Confirm top-level search `count` is not used as heat.
- [ ] Confirm user Markdown, JSON, and TXT agree.
- [ ] Confirm second same-day generation reuses the first result.
- [ ] Confirm no Cookie, API key, authorization header, or secret appears under `data/`.
