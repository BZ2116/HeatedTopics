# Zhihu Dual Source Implementation Report

Date: 2026-07-25
Worktree: `E:\.code\My\heatedTopics\heatedTopics\.worktrees\baidu-zhihu-daily-mvp`
Branch: `feature/baidu-zhihu-daily-mvp`

## Scope and commit history

The branch extends the cached-news workflow with two coordinated Zhihu
sources: an authenticated `zhihu_hot` (real hot board with question
details) and an anonymous `zhihu_daily` (latest + top stories with a
seven-day archive search). Cookie credentials are loaded only from the
local `ZHIHU_COOKIE` environment variable and never appear in Git,
logs, fixtures, cached files, smoke results, or `collection_status.json`.

| Task | Commit SHA | Subject |
|------|------------|---------|
| 1 | `595cc99` | feat: persist structured detail metadata |
| 2 | `9ebc01e` | feat: define zhihu hot authentication boundary |
| 3 | `2f52cce` | feat: collect real zhihu hot board |
| 4 | `978bcb3` | feat: collect zhihu question hot answers |
| 5 | `e5178b1` | feat: collect zhihu daily top stories |
| 6 | `7659f5e` | feat: support cached no-search providers |
| 7 | `cf130c8` | feat: register zhihu dual sources |

## Automated verification

| Stage | Total | Pass |
|-------|-------|------|
| Pre-feature baseline | 322 | 322 |
| Post-Task 5 (full suite) | 351 | 351 |
| Post-Task 6 (full suite) | 354 | 354 |
| Post-Task 7 (full suite) | 361 | 361 |
| Post-Task 8 (full suite) | 364 | 364 |

Focused verification (plan Task 8 Step 8):

```
uv run pytest tests/providers/test_zhihu_hot.py \
                 tests/providers/test_zhihu_daily.py \
                 tests/test_discovery.py \
                 tests/test_news_collection.py \
                 tests/test_news_recommendation.py \
                 tests/test_news_cli.py \
                 tests/test_news_smoke_validator.py -q
```

Result: 100 passed.

```
uv run python -m compileall -q src tests
git diff --check
```

Result: clean, no warnings from project code.

## Real `zhihu_hot` verification

`ZHIHU_COOKIE` is not present in the local `.env`. `check-zhihu-auth`
therefore returns the explicit `missing` status:

```json
{"status":"missing","command":"check-zhihu-auth","checked_at":"2026-07-25T21:54:27+08:00"}
```

Per plan Task 8 Step 4: "If it reports `missing` or `expired`, stop the
real smoke portion and ask the user to replace the local `.env` value.
Do not request the Cookie in chat." No live `zhihu_hot` collection was
attempted.

- Auth health status: `missing`
- Board source used: not exercised (no credential)
- Normalized, eligible, and rejected counts: not produced
- Detail success count: not produced
- Observed answer count range, capped at 5: not produced
- Main rejection reason codes: `auth_missing` would be emitted by
  `collect_news_daily` if the run were executed without a Cookie; the
  other five platforms would remain unaffected (verified by
  `test_missing_cookie_only_fails_zhihu_hot_collection`).

## Real `zhihu_daily` verification

`zhihu_daily` requires no credential and is exercised by the existing
MVP smoke collection (see the prior
`baidu-zhihu-daily-mvp-implementation-report.md`). Its `top_stories`
augmentation is exercised by automated tests (`latest_includes_top_stories_and_deduplicates_story_ids`,
`rank_articles_places_top_before_latest`).

## User matching verification

`discover_platform_articles` skips search for `supports_search=False`
providers and falls back to the most recent eligible snapshot within
48 hours. Three automated tests cover the contract:

- `test_no_search_provider_returns_current_matches_without_search`
- `test_no_search_provider_uses_active_snapshot_within_48_hours`
- `test_no_search_provider_rejects_snapshot_older_than_48_hours`

`NEWS_DISPLAY_ORDER` lists `zhihu_hot` between `baidu_hot` and
`zhihu_daily`. `NEWS_PLATFORMS` mirrors the same order.

## Credential isolation

`tools/validate_news_smoke.py` runs a `SECRET` regex scan across every
JSON file in the data root and rejects any file that matches. The
`SECRET` pattern was tightened so that JSON-style `"Cookie":"value"`
pairs (not only header-style `Cookie: value`) trigger the violation.

The new tests `test_smoke_validator_rejects_cookie_shaped_content` and
`test_smoke_validator_rejects_more_than_five_zhihu_answers` confirm:

- A JSON object containing a `Cookie`-shaped string fails validation.
- A `details/zhihu_hot_*.json` sidecar with more than 5 answer metadata
  records fails with `zhihu-answer-limit:<path>`.

`grep -n "private-cookie-value\|z_c0=local"` across `src`, `README.md`,
and `.env.example` returns no matches. The same values appear only
inside tests (for isolation assertions) and inside this implementation
plan.

The `test_detail_metadata_contains_no_cookie` and
`test_auth_http_failures_are_expired_without_leaking_cookie` tests in
`tests/providers/test_zhihu_hot.py` ensure that the Cookie value is
never embedded in `ItemDetail.content`, `ItemDetail.metadata`, or the
string representation of authentication exceptions.

## Known limitations

- `zhihu_hot` requires a locally maintained `ZHIHU_COOKIE`. Cookie
  lifetime is controlled by Zhihu and cannot be guaranteed indefinitely.
  Replacing the local `.env` value restores operation without code
  changes.
- The API hot board is preferred; HTML fallback activates only when the
  API JSON contract changes. The HTML question page fallback activates
  only when the API question/answers contract changes.
- The 48-hour stale snapshot fallback is bounded: when the latest
  eligible snapshot is older than 48 hours and no same-day items exist,
  `zhihu_hot` returns no results for that day rather than fabricating
  evidence.
- The implementation report intentionally records only measured counts
  and fixed status codes. Real titles, descriptions, answer bodies,
  Cookie values, response headers, and complete API payloads are not
  copied into this report.