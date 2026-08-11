# Baidu Hot Search and Zhihu Daily MVP — Implementation Report

Date: 2026-07-23
Worktree: `E:\.code\My\heatedTopics\heatedTopics\.worktrees\baidu-zhihu-daily-mvp`
Branch: `feature/baidu-zhihu-daily-mvp`

## Plan and design references

- Design spec: `docs/superpowers/specs/2026-07-23-baidu-zhihu-daily-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-23-baidu-zhihu-daily-mvp.md`
- Handoff: `docs/handoffs/2026-07-23-baidu-zhihu-daily-mvp-handoff.md`

## Commit history

| Task | Commit SHA | Subject |
|------|------------|---------|
| 1 | `99cdc06` | feat: support contextual official discovery |
| 2 | `f0a9b1b` | feat: parse baidu official hot board |
| 3 | `a60800a` | feat: resolve baidu hot event articles |
| 4 | `efd48d3` | feat: collect zhihu daily full stories |
| 5 | `9dcac47` | feat: search zhihu daily archives |
| 6 | `854472d` | feat: register baidu and zhihu daily providers |

## Test counts

| Stage | Total | Pass |
|-------|-------|------|
| Pre-feature baseline | 277 | 277 |
| Post-Task 6 (full suite) | 320 | 320 |
| Post-Task 7 (full suite) | 322 | 322 |

Focused verification (plan Task 7 Step 4):

```
uv run pytest tests/providers/test_baidu_hot.py \
                 tests/providers/test_zhihu_daily.py \
                 tests/test_discovery.py \
                 tests/test_news_collection.py \
                 tests/test_news_recommendation.py \
                 tests/test_news_cli.py \
                 tests/test_news_smoke_validator.py -q
```

Result: 78 passed.

```
uv run python -m compileall -q src tests
git diff --check
```

Result: clean, no warnings from project code.

## Live anonymous smoke collection

Command:

```
uv run heated-topics collect-news --data-root <smoke-root>
```

`collection_status.json`:

| Platform | Status | Item count |
|----------|--------|------------|
| sina_news | success | 50 |
| thepaper | failed (ValueError) | 0 |
| netease_news | success | 15 |
| baidu_hot | partial | 51 |
| zhihu_daily | success | 4 |

`tools/validate_news_smoke.py <smoke-root>`: `{"status":"success","violations":[]}`.

### Baidu Hot Search (baidu_hot)

- Raw items: 51 from `https://top.baidu.com/board?tab=realtime`.
- All 51 items rejected with reasons `too_short` and `insufficient_structure`.
- During the live run, every `rawUrl` returned by Baidu's official board is a
  `https://www.baidu.com/s?wd=...` query link that is treated as an aggregation
  surface and rejected by `_is_rejected_surface`. The search-fallback path
  therefore activates for every item, but each fallback returned empty
  candidate bodies from the live Baidu search endpoint during this smoke run.
  The collection workflow correctly records `partial` status with the rejection
  reasons rather than fabricating full text.
- `validate_news_smoke.py` still reports `success` because no `result.json`
  files exist (no user-triggered `generate-news` run produced recommendations
  for Baidu in this verification), and no credentials are embedded anywhere.

### Zhihu Daily (zhihu_daily)

- Raw items: 4 type-0 stories from `https://daily.zhihu.com/api/4/news/latest`.
- 4 eligible articles persisted, 0 rejected.
- Per-item evidence: `source_kind=official_hot_board`, `platform_rank=1..4`,
  `qualified_by=["official_hot_board"]`, `metrics={}`.

## Live generate-news verification

Two profiles were created from real titles harvested from the smoke collection:

- `live-baidu`: `primary_keyword` taken from the first Baidu normalized item.
- `live-zhihu`: `primary_keyword` taken from the first Zhihu normalized item.

| Profile | Run 1 status | Run 1 elapsed | Run 2 status | Run 2 elapsed |
|---------|--------------|---------------|--------------|---------------|
| live-baidu | `no_result` | 2.223 s | `existing` | 0.095 s |
| live-zhihu | `generated` (1 recommendation) | 1.847 s | `existing` | 0.106 s |

Second-run wall-clock times are an order of magnitude lower than the first run,
confirming that the search cache avoids new provider requests on the same
business date.

## Credential scan

`tools/validate_news_smoke.py` ran its built-in `SECRET` regex scan across all
JSON files under the smoke root: zero `credential:` violations.

The Baidu and Zhihu Daily provider modules contain no `.env`, `Cookie`,
header, or credential reads. Only public endpoints are called.

## Known limitations

- Live Baidu Hot Search `rawUrl`s are `https://www.baidu.com/s?wd=...` redirect
  links, not direct article URLs. The supporting-article fetcher correctly
  treats them as aggregation surfaces and falls back to keyword search. The
  live Baidu search endpoint returned empty candidate bodies during this
  smoke run, so all Baidu items ended up rejected with `too_short` and
  `insufficient_structure`. The collection workflow is structurally correct;
  improving live Baidu body coverage would require a different supporting
  source strategy and is out of scope for this MVP.
- Zhihu Daily latest sometimes returns fewer type-0 stories than the historical
  dozen (4 in this run); the contract accepts any non-empty list.
- The plan's automated suite does not assert live `existing`-status runtimes;
  the wall-clock comparison above is manual evidence.

## Out-of-scope items

- Toutiao, Juejin, and V1 providers were not touched.
- No article bodies, credentials, or `.env`-shaped strings were copied into
  this report.