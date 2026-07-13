# V1 Task 1 Report: Parse Real Toutiao Search DOM

## RED

- Replaced `tests/fixtures/toutiao_search.json` with a sanitized `{count, dom}` response containing two current OpenAI result cards and stable real group IDs.
- Added assertions for both parsed cards plus title, canonical group URL, summary, source, publication time, stable `group_id`, `search_rank`, and independence from top-level `count`.
- Command: `uv run pytest tests/providers/test_toutiao.py -q`
- Expected failure: DOM response produced `[]`; 1 failed, 8 passed.

## GREEN

- Added a focused standard-library `HTMLParser` for DOM result cards.
- DOM results canonicalize URLs to `https://www.toutiao.com/group/{group_id}/`, retain `group_id` and extracted source in `raw_payload`, preserve the 24-hour publication filter, and expose rank only as `metric_name="search_rank"`.
- Existing `data` parsing remains the compatibility fallback, including reviewed engagement and time behavior.
- Command: `uv run pytest tests/providers/test_toutiao.py -q`
- Result: 9 passed.

## Full suite

- Command: `uv run pytest -q`
- Result: 42 passed.
- `git diff --check` passed (Git emitted only the repository's LF-to-CRLF checkout notices).

## Files

- `src/heated_topics_v3/providers/toutiao.py`
- `tests/providers/test_toutiao.py`
- `tests/fixtures/toutiao_search.json`
- `.superpowers/sdd/v1-task-1-report.md`

## Concerns

- During capture on 2026-07-13, direct requests from this environment returned Toutiao's full SSR HTML rather than the previously observed incremental JSON response. The sanitized fixture uses current card metadata captured from that live response but keeps only the stable semantic card HTML needed by the `{count, dom}` contract; ephemeral classes, signatures, search IDs, images, and tracking query parameters were removed.
- Parser behavior intentionally depends on stable group links or `data-group-id`, not Toutiao's generated CSS class names. If Toutiao removes both identifiers from DOM cards, another fixture refresh will be needed.
