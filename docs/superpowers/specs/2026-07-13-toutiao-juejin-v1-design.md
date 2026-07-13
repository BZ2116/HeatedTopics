# Toutiao and Juejin V1 Design

## Goal

Deliver a usable first version of hot-topic recommendation using only Toutiao and Juejin. The version collects both official boards and article details, matches a user's saved `primary_keyword`, and writes daily machine-readable and human-readable artifacts.

## Sources

### Toutiao

1. Collect the anonymous official Top 50 board and preserve rank and `HotValue`.
2. Search Toutiao once with the user's exact `primary_keyword`.
3. Parse current search responses from the returned `dom` HTML and retain article `group_id`, title, URL, summary, source, and publication time when available.
4. Cross-check search results against the daily official board using `group_id`, canonical URL, then normalized title.
5. A matching board result is Level 1 and inherits the board rank and `HotValue`.
6. A non-matching search result remains visible as Level 3 with the notice `来自头条关键词搜索，未发现官方热榜证据`.
7. The search response's top-level `count` is only the number of returned results and is never treated as heat.
8. Comment totals may be collected as supporting metadata, but they do not promote a result in V1.

### Juejin

1. Collect the official hot-rank list and its public engagement metrics.
2. Fetch full article text through the detail API with page, summary, and title fallbacks.
3. Match the user's `primary_keyword` against title, summary, and detail.
4. Matched official hot-rank records are Level 1.

## User Matching

Load a JSON user profile containing `primary_keyword`. Matching is deterministic Unicode-normalized substring matching over title, summary, and collected detail text. V1 does not call an LLM and does not use the rest of the profile for ranking.

## Ordering and Duplication

- Display Toutiao before Juejin.
- Preserve official order inside each Level 1 platform section.
- Toutiao Level 3 search results follow the Level 1 results in search-return order.
- Do not rank across platforms.
- Do not deduplicate the same event across platforms.

## Output

Daily collection artifacts:

```text
data/daily_hot_lists/<date>/
├── raw/toutiao.json
├── raw/juejin.json
├── normalized/toutiao.json
├── normalized/juejin.json
├── details/<platform>_<sequence>.txt
└── collection_status.json
```

User result artifacts:

```text
data/user_results/<user_id>/<business-date>/
├── report.md
├── result.json
└── topics/<platform>_<sequence>.txt
```

Each TXT contains only title, platform, heat level, publication time, collection time, and detailed content. Missing content falls back to source summary and then title; no text is invented.

## Execution

V1 exposes Python functions and manual CLI commands for:

- collecting the two official boards and all details;
- generating one cached recommendation result per user and business day.

Scheduling, frontend behavior, Baidu, Weibo, Zhihu, and Qianfan are outside V1.

## Failure Handling

- The two platforms fail independently.
- Raw responses are saved separately from normalized records.
- Detail failures use source-provided fallbacks.
- Search failure does not remove official-board matches.
- User results are written atomically and same-day completed results are reused.
- Secrets and request credentials are never serialized.

## Verification

V1 is complete when:

1. Real anonymous Toutiao and Juejin boards are collected.
2. Detail TXT exists for every normalized board item.
3. Current Toutiao `dom` search responses produce real article records.
4. Board overlap receives Level 1 evidence; non-overlap remains Level 3.
5. One real profile produces Markdown, JSON, and topic TXT artifacts.
6. A repeated same-day request returns the stored result without new search calls.
7. Automated tests pass and a manual real-data smoke run records actual counts and failures.
