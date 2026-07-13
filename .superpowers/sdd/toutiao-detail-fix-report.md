# Toutiao detail fix report

## Root cause

The V1 CLI constructed `ToutiaoProvider(client)` without a rendered fetcher. Static
Toutiao HTML commonly contains no server-rendered `<article>`, so every such item
fell through to the hot-board summary or title. During the fix, the first real
smoke run exposed a second defect: a JavaScript newline inside the Playwright
`page.evaluate` expression was not escaped at the Python string boundary and
caused `Page.evaluate: SyntaxError`.

## Implementation

- The anonymous default provider now owns a lazy `PlaywrightArticleRenderer`.
- One background event loop, Chromium browser, and browser context are shared for
  the provider lifetime. Page concurrency is capped at three.
- `collection.py` still persists each completed detail independently and closes
  every provider in `finally`, including partial and failed platform runs.
- Trending URLs discover and follow the first event-detail article before body
  extraction. Direct article/group pages are extracted in place.
- A rendered result is only marked `full_text` when cleaned content has at least
  120 characters and two non-empty lines. Obvious navigation-only content is
  removed; insufficient content falls back to the source summary/title.
- Browser/import/evaluation failures remain isolated per item. Sanitized failure
  codes are included in the platform `partial` status without exception messages,
  URLs, headers, cookies, or credentials.

## TDD and verification

RED tests were observed for default CLI wiring, meaningful rendered-body
selection, navigation-only rejection, renderer close, provider close, shared
renderer initialization, three-page concurrency, trending-to-article following,
escaped evaluation JavaScript, and sanitized partial diagnostics.

Final verification:

```text
uv run pytest -q
146 passed in 2.51s

git diff --check
exit 0
```

## Real smoke evidence

Independent output root (existing user data was not overwritten):

`smoke_data/toutiao-detail-fix-verified-20260713`

The Toutiao platform status is `success`; all three details are multi-line
`full_text`:

| Item | Extraction | Characters | Lines |
|---|---|---:|---:|
| 高盛：中国股票出现“轮动信号” | Playwright followed event article | 2976 | 45 |
| 中国首个禁售燃油车省份确认 | Playwright followed event article | 300 | 2 |
| 中国电力技术创新位居全球首位 | Playwright direct article page | 188 | 4 |

Machine-readable evidence is in `smoke-summary.json`; the combined readable
evidence is in `smoke-report.md`; source text files are under
`daily_hot_lists/2026-07-13/details/`.

## Reviewer hardening follow-up

The renderer no longer falls back to `document.body.innerText`. If no trusted
article container is found it returns empty text, while a trending page may still
expose and follow its event-detail article link. Final classification now removes
the item title from the substantive-character count and rejects short UI lines
such as login/App prompts, comment controls, reply links, hot-list navigation,
and footer actions. A normal two-line article over 300 characters remains valid.

The independent follow-up smoke root is:

`smoke_data/toutiao-detail-reviewer-fixed-20260713`

It captured three current items as `full_text`: 1158 characters / 12 lines,
2976 / 45, and 188 / 4. The first two followed event-detail article links; the
third was a direct article page. `collection_status.json` intentionally records
Juejin as failed because this Toutiao-only smoke supplies a fake Juejin provider
that always raises `RuntimeError`; it is not evidence of a production Juejin
regression.
