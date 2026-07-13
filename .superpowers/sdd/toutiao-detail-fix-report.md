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

The reviewer's exact single-long-line reproduction is also covered: the title
followed by eight repetitions of “打开今日头条查看更多精彩内容，登录后关注作者并参与评论。”
now degrades to `partial:RenderedContentTooShort`. Detection uses repeated UI
marker count and character coverage, so a genuine article that mentions login
and commenting once is still accepted. The final independent regression root is
`smoke_data/toutiao-detail-reviewer-exact-fixed-20260713`; its three current
Toutiao samples are 1158/12, 2976/45, and 188/4 characters/lines and all are
`success/full_text`. Juejin was not invoked in this Toutiao-only regression, as
recorded in its `smoke-summary.json`.

## Trending aggregate coverage follow-up

A clean 50-item collection exposed 17 trending pages that had no usable article
body at snapshot time. Five live DOM samples shared the same explicit structure:

- `事件详情`: 34–72 characters; four samples linked video, one linked article;
- optional `事件脉络`: 132 characters in the sampled page where present;
- `相关内容`: 215, 757, 229, 289, and 440 characters;
- `网友讨论`: a separate 475–776-character block that must not be captured.

The renderer now returns `.block-container` title/text pairs, never the body. For
trending pages only, it concatenates `事件详情`, `事件脉络`, and `相关内容`, and
stops before `网友讨论`, `头条热榜`, `推荐`, or `猜你喜欢`. Following a discovered
article remains the first choice. It also waits up to four seconds for Toutiao's
lazy `.topic-related-list-wrapper`/timeline before taking the bounded snapshot;
this addressed article cards that appeared before their related-content block.

The final independent retry is
`smoke_data/toutiao-trending-bounded-17-final-20260713`. All 17 previously partial
items are now `success/full_text` (259–4610 characters, 12–21 lines), with zero
remaining failure types. Combined with the original 33 full-text items, this
projects to 50/50 for the same captured board. An automated check confirmed none
of the 17 texts contains `网友讨论`, `头条热榜`, `换一换`, or the login-comment
prompt. Thresholds were unchanged.
