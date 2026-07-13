# Toutiao and Juejin V1 Implementation Report

## Delivered workflow

The installed `heated-topics` command exposes the two approved manual paths:

```powershell
uv run heated-topics collect-v1 --data-root data
uv run heated-topics generate-v1 --data-root data --profile data/profiles/v1-smoke-ev-profile.json
```

Both commands emit one compact JSON object to stdout. Argument failures return
exit code 2 and runtime or terminal workflow failures return exit code 1 with
only a fixed error code or exception class. No exception message, profile
contents, request header, Cookie, authorization value, or credential is emitted.
The V1 client is anonymous and does not load `.env`.

## Automated verification

- Baseline before Task 5: `uv run pytest -q` -> `81 passed in 1.22s`.
- CLI RED: `uv run pytest tests/test_cli.py -q` -> `7 failed`; every failure was
  the expected missing `heated_topics_v3.cli` import before production code.
- CLI GREEN: `uv run pytest tests/test_cli.py -q` -> `7 passed in 0.62s`.
- Full suite after CLI implementation: `uv run pytest -q` -> `88 passed in
  1.40s`.
- Review RED: `uv run pytest
  tests/test_cli.py::test_help_uses_normal_success_exit_without_failure_json -q`
  -> `1 failed`; help incorrectly returned 2 instead of 0.
- Review GREEN: `uv run pytest tests/test_cli.py -q` -> `8 passed in 0.51s`;
  `uv run heated-topics collect-v1 --help` printed normal help and exited 0.
- Final full suite after the review fix: `uv run pytest -q` -> `89 passed in
  1.33s`.
- The installed entry point itself was used for every real smoke command below.

## Real anonymous smoke run

The smoke ran on 2026-07-13 in Asia/Shanghai against the current public Toutiao
and Juejin endpoints, writing beneath the repository worktree at
`E:\.code\My\heatedTopics\heatedTopics\.worktrees\hot-topic-workflow\data`.

### Collection

Command:

```powershell
uv run heated-topics collect-v1 --data-root data
```

The command started at `2026-07-13T14:27:48.742422+08:00`, exited 0, and
reported `partial` in 6.261 seconds:

- Toutiao: 50 raw and 50 normalized official-board items; 50 detail files;
  0 full-detail successes and 50 summary/title fallbacks, therefore platform
  status `partial`.
- Juejin: 45 raw and 45 normalized official-rank items; 45 detail files;
  45 full-detail successes and 0 fallbacks, therefore platform status
  `success`.

Representative collection paths:

- Relative raw: `data/daily_hot_lists/2026-07-13/raw/toutiao.json` and
  `data/daily_hot_lists/2026-07-13/raw/juejin.json`.
- Relative normalized: `data/daily_hot_lists/2026-07-13/normalized/toutiao.json`
  and `data/daily_hot_lists/2026-07-13/normalized/juejin.json`.
- Relative detail: `data/daily_hot_lists/2026-07-13/details/toutiao_1.txt` and
  `data/daily_hot_lists/2026-07-13/details/juejin_1.txt`.
- Absolute status:
  `E:\.code\My\heatedTopics\heatedTopics\.worktrees\hot-topic-workflow\data\daily_hot_lists\2026-07-13\collection_status.json`.

All four raw/normalized JSON files parsed as UTF-8 JSON. Every one of the 95
normalized records had a nonempty sequence-aligned detail TXT.

### Profile and generation

The saved real profile is
`data/profiles/v1-smoke-ev-profile.json`. Its exact primary keyword,
`禁售燃油车`, was selected from the current Toutiao board so both board overlap
and non-overlap behavior could be observed.

First generation:

```json
{"status":"generated","command":"generate-v1","user_id":"v1-real-smoke-ev-creator","business_date":"2026-07-13","recommendation_count":7,"potential_topic_count":3,"elapsed_seconds":1.02}
```

Second generation:

```json
{"status":"existing","command":"generate-v1","user_id":"v1-real-smoke-ev-creator","business_date":"2026-07-13","recommendation_count":7,"potential_topic_count":3,"elapsed_seconds":0.128}
```

The generated result has 7 official-board-overlap Level 1 Toutiao records and 3
non-overlap Level 3 Toutiao search records. It contains 10 topic TXT files. The
absolute result directory is
`E:\.code\My\heatedTopics\heatedTopics\.worktrees\hot-topic-workflow\data\user_results\v1-real-smoke-ev-creator\2026-07-13`.

Cache reuse was additionally checked around another `existing` invocation. The
`result.json` modification-time ticks remained `639195211200874834`, and its
SHA-256 remained
`03B48D90A8533AB092A34D4E50D2F851CECDFA08CED1877C12F42481FD1BAF4E`.
The cached file was neither regenerated nor rewritten.

## Artifact and data-contract inspection

- A fresh anonymous Toutiao search at
  `2026-07-13T14:33:19.529971+08:00` returned a 244,082-character current DOM,
  top-level `count=10`, and 10 parsed records inside the 24-hour window.
- Every search item used `metric_name="search_rank"`, with values exactly 1
  through 10 matching item rank. The top-level response count was not copied or
  interpreted as heat.
- The generated `report.md` and `result.json` exactly matched their deterministic
  renderers. Each of the 10 topic TXT files exactly matched the corresponding
  structured item and contained only the approved six fields. There were no
  missing or extra topic files.
- Formal and potential counts, titles, platforms, heat levels, collection times,
  publication times, and detail content therefore agree across Markdown, JSON,
  and TXT.

## Credential scan and endpoint limitations

All 156 UTF-8 text/JSON files beneath `data/` were scanned for Cookie and
authorization headers, API-key/token/secret assignments, OpenAI-style keys, AWS
access keys, JWTs, populated bearer credentials, and populated Cookie headers.
The high-confidence credential-value scan found 0 matches.

A deliberately broad name-only scan found 12 occurrences. Manual inspection
showed four public Juejin article code examples (and their copied report/topic
renderings): variable names such as `token`/`apiKey`, an authorization template,
and the explicit dummy placeholder `sk-xxxxxxxx`. None is a request credential,
and none has a credential-shaped value.

Toutiao's public article responses returned HTTP 200 HTML but no server-rendered
`<article>` element. Because the CLI does not configure a browser renderer, all
50 Toutiao detail attempts correctly fell back to source summaries/titles and
were recorded as partial. The official board, HotValue, keyword-search DOM,
cross-validation, and user artifacts remained usable. Juejin's public detail API
returned full text for all 45 records.

An exploratory `AI` profile demonstrated a second endpoint characteristic: the
DOM parser found 10 structurally valid cards, but all were older than V1's
24-hour search window and were therefore excluded. The final smoke profile used
a current-board keyword and produced 10 current search records, so this did not
block the required workflow proof.
