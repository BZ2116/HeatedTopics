# Task 3 Report: Filesystem Repository

## Status

Complete.

## RED / GREEN

- RED: `uv run pytest tests/test_storage.py -q` failed during collection with `ModuleNotFoundError: No module named 'heated_topics_v3.storage'`.
- First GREEN attempt: 5 tests passed and 2 failed because Windows rejected `os.fsync` on a read-only file descriptor (`OSError: [Errno 9] Bad file descriptor`).
- GREEN: after opening files in writable binary mode for flushing, `uv run pytest tests/test_storage.py -q` passed: 7 passed.

## Full Suite

- `uv run pytest -q`: 25 passed.
- `git diff --check`: clean.

## Files

- `src/heated_topics_v3/storage.py`
- `tests/test_storage.py`

## Implementation Notes

- Deterministic daily raw, normalized, detail, status, profile-compatible, and user-result paths follow the approved design layout.
- JSON uses UTF-8, `ensure_ascii=False`, two-space indentation, and a trailing newline.
- Recursive JSON conversion uses `dataclasses.asdict` and removes case-insensitive cookie, API key, secret, authorization, and proxy-authorization fields.
- Snapshot and recommendation bundle loaders reconstruct immutable Task 1 contracts.
- User results are written to operation-specific UUID temporary directories, file contents are flushed with `fsync`, and complete directories are atomically published with `Path.replace`.
- Existing completed directories are returned without invoking or overwriting via the writer callback; failed operations remove only their own temporary directory.

## Self-review / Concerns

- No blocking concerns.
- Atomic directory replacement is intentionally scoped to publishing a previously absent final directory. Concurrent publishers defer to the completed final directory if another writer wins the race.

## Review Fixes

- RED: `uv run pytest tests/test_storage.py -q` produced 2 failures and 7 passes. Nested `x-api-key`, `apiKey`, `apikey`, and `QIANFAN_SECRET_KEY` fields survived sanitization, and a simulated Windows publish-race `OSError` escaped after a competing final directory appeared.
- GREEN: `uv run pytest tests/test_storage.py -q` passed with 9 tests.
- Secret-field filtering now normalizes camelCase and punctuation into key tokens, recognizes API-key, cookie, authorization, and secret aliases recursively, and never scans or alters harmless string values.
- Atomic publication now catches the relevant `OSError` family, re-checks the final directory, suppresses the error only when another completed directory exists, removes only the current temporary directory, and otherwise re-raises.
- Review full suite: `uv run pytest -q` passed with 27 tests; `git diff --check` was clean.
