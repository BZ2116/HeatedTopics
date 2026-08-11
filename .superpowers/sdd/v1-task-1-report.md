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

## Initial concerns

- Initial capture requests containing only `keyword` returned full SSR HTML. The review follow-up identified and fixed the missing JSON request parameters.
- The first fixture and parser assumed direct group links or `data-group-id`; the review follow-up replaced both with the current response structure and metadata contracts.

## Review follow-up

- Root cause confirmed: the JSON DOM response requires `keyword`, `pd=information`, `source=search_subtab_switch`, `from=information`, `format=json`, `count=10`, and `offset=0`. A live request with those exact parameters returned HTTP 200, `application/json`, `count=10`, and a 240 KB `dom` value.
- Replaced the idealized fixture with two sanitized current `div.result-content` cards preserving `cr-params`, `data-log-extra`, jump links, nested `l-card-title`/`l-paragraph`/author structures, `<img>`, and `<br>`. Only tokens, signatures, tracking payloads, remote media URLs, scripts, styles, and unrelated cards were removed.
- RED 1: focused suite failed because the request contained only `keyword`; after the request fix, RED 2 failed because the faithful cards produced no items and unmatched `<img>`/`<br>` scopes changed source to `Source recent`.
- GREEN: parser now uses matching `(tag, target, card-root)` frames, ignores HTML void elements for scope purposes, reads stable metadata from `cr-params` and `data-log-extra`, and supports encoded jump URLs.
- Count provenance uses sentinel `777`; every DOM item asserts `value == rank`, `metric_name == "search_rank"`, metrics equal `{"search_rank": rank}`, and no value equals the sentinel count.
- Focused command: `uv run pytest tests/providers/test_toutiao.py -q` -> 10 passed.
- Full command: `uv run pytest -q` -> 43 passed.
- Live smoke test after GREEN parsed three OpenAI cards within the 24-hour window, including canonical group URLs, timestamps, and author sources.

### Updated concerns

- The JSON endpoint contract is parameter-sensitive. The exact production parameters are now covered by a request assertion.
- The parser relies primarily on `result-content`, `cr-params`, `data-log-extra`, `l-card-title`, `l-paragraph`, and author click metadata observed in the current response, while retaining direct group-link compatibility. A future wholesale template change will require a fixture refresh.
