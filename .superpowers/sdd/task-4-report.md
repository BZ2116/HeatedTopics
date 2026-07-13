# Task 4 Report: Toutiao and Juejin Providers

## RED

- `uv run pytest tests/providers/test_toutiao.py tests/providers/test_juejin.py -q`
- Failed during collection with `ModuleNotFoundError: heated_topics_v3.providers.common`, confirming the new provider surface did not exist.
- A later detail-status test failed with provider-specific method names instead of the contract-level `success`/`partial` statuses.

## GREEN

- Added immutable `ProviderCapture(raw_text, raw_suffix, items)`.
- Added Toutiao hot-board parsing, exactly-one-keyword search, explicit engagement metrics, timestamp-aware 24-hour filtering, and detail fallbacks: static article, rendered article, summary, title.
- Added Juejin rank parsing and detail fallbacks: detail API, article HTML, summary, title.
- Added sanitized fixture responses with two or more rows, numeric heat, missing values, and no credentials or personal data.
- Focused result: `5 passed`.

## Full tests

- `uv run pytest -q`: `32 passed`.
- `git diff --check`: clean (line-ending notices only).

## Files

- `src/heated_topics_v3/providers/common.py`
- `src/heated_topics_v3/providers/toutiao.py`
- `src/heated_topics_v3/providers/juejin.py`
- `src/heated_topics_v3/providers/__init__.py`
- `tests/providers/test_toutiao.py`
- `tests/providers/test_juejin.py`
- `tests/fixtures/toutiao_hot_board.json`
- `tests/fixtures/toutiao_search.json`
- `tests/fixtures/juejin_hot_rank.json`

## Concerns

- Rendered Toutiao extraction is injected rather than owning a browser lifecycle, keeping the provider testable and leaving orchestration responsible for rendering.
- Publication timestamps are filtered only when present, as required; undated search results remain eligible.

## Review-fix RED

- Added focused regressions for malformed Toutiao publication timestamps, sparse Juejin metrics, Juejin API network/non-JSON/bad-shape failures, request article ID, page failure, and both title-only fallbacks.
- Focused run: `4 failed, 6 passed`. Failures matched the review findings: timestamp parsing raised, absent counters became zero, and API failures escaped.

## Review-fix GREEN

- Moved shared numeric and article parsing helpers into `providers/common.py`; providers no longer import private sibling helpers.
- Juejin now attempts the article page after HTTP, decoding, and payload-shape errors, then falls back to summary/title.
- Juejin metrics now contain only counters present and numeric in the response.
- Malformed Toutiao publication timestamps are deliberately retained as undated results.
- Focused result: `11 passed`; full result: `38 passed`; `git diff --check` clean apart from Windows line-ending notices.
