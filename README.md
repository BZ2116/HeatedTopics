# HeatedTopics V1

HeatedTopics V1 anonymously collects the official Toutiao and Juejin hot lists,
then generates a deterministic daily recommendation report from one saved
`primary_keyword`. V1 does not load `.env`, send a Cookie, or require an API key
or other credentials.

## Quick start

Install the project and collect the current public boards into `data/`:

```powershell
uv sync
uv run heated-topics collect-v1 --data-root data
```

Create a UTF-8 JSON profile using the fields shown in
`config/profiles/tech_ai_creator.json`, then generate the result twice to observe
same-business-day cache reuse:

`user_id` is a single filesystem-safe identifier: 1-64 ASCII letters, digits,
underscores, or hyphens, beginning with a letter or digit.

```powershell
uv run heated-topics generate-v1 --data-root data --profile config/profiles/tech_ai_creator.json
uv run heated-topics generate-v1 --data-root data --profile config/profiles/tech_ai_creator.json
```

Each workflow execution writes exactly one JSON status object to stdout. Collection reports
per-platform item counts. Generation returns `generated` or `no_result` on its
first completed run and `existing` when that user/business-date result is already
cached. Invalid arguments and failures return a nonzero exit code with a
sanitized JSON error.

## Output layout

```text
data/
|-- daily_hot_lists/<date>/
|   |-- raw/toutiao.json
|   |-- raw/juejin.json
|   |-- normalized/toutiao.json
|   |-- normalized/juejin.json
|   |-- details/toutiao_<sequence>.txt
|   |-- details/juejin_<sequence>.txt
|   `-- collection_status.json
`-- user_results/<user_id>/<business-date>/
    |-- report.md
    |-- result.json
    `-- topics/<platform>_<sequence>.txt
```

Toutiao is displayed before Juejin. V1 does not include a scheduler, frontend,
LLM ranking, or any other platform.

## Cached News Workflow

In addition to the V1 two-platform workflow, this branch ships an anonymous
three-platform cached news pipeline (Sina News, The Paper, NetEase News). The
news workflow never sends a Cookie, an Authorization header, an API key, or any
`.env` value.

```powershell
uv run heated-topics collect-news --data-root data
uv run heated-topics generate-news --data-root data --profile config/profiles/tech_ai_creator.json
```

The news workflow produces a distinct `news_user_results/` tree and never writes
into the V1 `user_results/` tree, so V1 and news results can coexist on the same
business date.

### Data layout for the news workflow

```text
data/
|-- daily_hot_lists/<date>/
|   |-- raw/<platform>.<suffix>      # captured once per day per platform
|   |-- normalized/<platform>.json   # validated official-board records
|   |-- eligible/<platform>.json     # only full_text + verified heat evidence
|   |-- rejected/<platform>.json     # reasons for each rejected record
|   |-- details/<platform>_<item_id>.txt
|   `-- collection_status.json
|-- active_snapshots/<platform>.json # atomic eligible pointer per platform
|-- search_cache/<date>/<platform>/<sha256(keyword)>/
|   `-- status.json                  # success/empty/failed cache per keyword
`-- news_user_results/<user_id>/<business-date>/
    |-- report.md
    |-- result.json
    `-- topics/<platform>_<sequence>.txt
```

### Result limits and guarantees

* Each of `sina_news`, `thepaper`, `netease_news`, `zhihu_hot`, and
  `zhihu_daily` returns at most `MAX_RESULTS = 20` articles per user request.
* `zhihu_daily` heat evidence is rank-only official archive data
  (`platform_rank`, eight-digit `recommendation_date`), with empty metrics.
  Search is bounded to a seven-day archive scan that caches up to 60 unique
  type-0 stories per `(keyword, collected_at date)`; later pages slice the
  cache without new HTTP calls.
* Both providers are anonymous and cookie-free: no `.env`, Cookie, header, or
  credential is read, sent, or persisted.
* Formal results are constructed only from `QualifiedArticle` records whose
  detail `content_status` is `full_text` and whose heat evidence contains a
  non-empty `qualified_by` set; `summary` and `title_only` records never become
  formal recommendations.
* Search is skipped when a platform already has at least `MIN_RESULTS = 5`
  matched cached records; otherwise the search runs in pages of
  `SEARCH_PAGE_SIZE = 15` and stops at most `MAX_SEARCH_CANDIDATES = 60` unique
  candidates or `MAX_RESULTS = 20` qualified records.
* The active eligible snapshot is only reused when it is at most 48 hours old,
  otherwise the cached board is treated as missing.

### Deferred

Tencent News is intentionally deferred for this batch because no confirmed
anonymous keyword search endpoint is currently available.

`baidu_hot` is temporarily removed from `NEWS_PLATFORMS` because every hot
board event links to a Baidu search-result page rather than a real article
URL, and the `s?wd=` fallback path is currently blocked by Baidu's captcha
wall. The `BaiduHotProvider` source file remains in `providers/baidu_hot.py`
and its unit tests in `tests/providers/test_baidu_hot.py` are kept so the
provider can be re-registered once a non-captcha search path is wired in.

### Zhihu sources

`zhihu_daily` is anonymous. `zhihu_hot` needs a locally maintained
`ZHIHU_COOKIE` in `.env`.

Check it without writing the Cookie or response body:

```powershell
uv run heated-topics check-zhihu-auth
```

Valid output:

```json
{"status":"valid","command":"check-zhihu-auth","checked_at":"2026-07-25T20:00:00+08:00"}
```

If the status is `missing` or `expired`, replace only the local `.env` value
and rerun the check. `collect-news` isolates this failure from every other
platform.
