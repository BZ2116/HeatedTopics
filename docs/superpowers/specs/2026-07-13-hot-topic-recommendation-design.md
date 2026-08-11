# Hot Topic Recommendation Design

## Objective

Build the collection and recommendation-generation layer for a downstream hot-topic recommendation feature. The first iteration is manually triggered and must run the complete workflow once. Scheduling and frontend behavior are out of scope.

The workflow favors recall over strict verification. It distinguishes confirmed hot-list topics, inferred hot topics, and potential topics so downstream consumers can present uncertainty honestly.

## First-Iteration Scope

The first iteration must:

1. Collect complete hot lists from Toutiao, Baidu Hot Search, Juejin, Weibo, and Zhihu.
2. Save each platform's raw response and normalized records.
3. Collect detail text for every hot-list record.
4. Load a user profile and match records using its `primary_keyword`.
5. Search Toutiao once with the user's `primary_keyword` and collect returned detail text.
6. Use Baidu Qianfan web search as the final discovery fallback.
7. Classify results into three heat levels and record factual status.
8. Generate Markdown, structured JSON, and one TXT file per topic.
9. Reuse an existing result when the same user is requested again in the same business day.
10. Expose a Python function and CLI command for downstream integration and manual testing.

The first iteration does not include:

- A persistent scheduler or Windows Task Scheduler configuration.
- Frontend pages, polling, loading states, or interaction behavior.
- Automatic retention cleanup.
- LLM-based relevance scoring.
- Cross-platform ranking or deduplication.
- Advanced full-profile ranking. This may be added later if keyword matching produces too many results.

## Platform Roles

Toutiao and Baidu Hot Search are the primary hot-list sources.

| Platform | Hot-list collection | Keyword search | Detail strategy | Role |
|---|---|---|---|---|
| Toutiao | Stable | Supported | Reuse existing article extraction with rendered-page and summary fallbacks | Primary source |
| Baidu Hot Search | Stable | Not supported | Use the hot explanation embedded in the board page | Primary source |
| Juejin | Stable | Not used | Reuse the article detail API and page fallback | Narrow technical supplement |
| Weibo | Requires `WEIBO_COOKIE` | Not used for user discovery | Reuse topic-search detail extraction with hot-list fallback | Auxiliary source |
| Zhihu | Requires `ZHIHU_COOKIE` | Not used for user discovery | Reuse answer API extraction with hot-list fallback | Auxiliary source |

Public news pages and Baidu Qianfan are discovery and supporting-information sources, not daily hot-list sources.

The fixed platform presentation order is:

1. Toutiao
2. Baidu Hot Search
3. Juejin
4. Weibo
5. Zhihu

Platforms remain independent. The same event may be shown once per platform, and no cross-platform heat comparison is performed.

## User Profile

Each user has a stable JSON profile:

```json
{
  "user_id": "user_001",
  "primary_track": "人工智能",
  "secondary_track": "AI应用与效率工具",
  "persona": "面向普通职场人的AI工具测评博主",
  "primary_keyword": "AI工具",
  "updated_at": "2026-07-13T00:00:00+08:00"
}
```

`primary_keyword` is explicitly stored and manually editable. The first iteration uses only this field to match hot-list titles, summaries, and collected detail text. It does not call an LLM for relevance decisions.

The remaining profile fields are retained for future ranking and for constructing the Qianfan fallback query. They do not restrict platform retrieval.

## Heat Levels

### Level 1: Confirmed Hot List

A topic is Level 1 when it has traceable official hot-list evidence, including its platform, list name, rank or heat value, source URL, and collection time.

### Level 2: Inferred Hot Topic

A topic is Level 2 when it is not confirmed on an official board but has a traceable heat signal. In the first iteration this primarily applies to Toutiao keyword-search results with an explicit heat, read, comment, like, or other engagement metric.

No numeric threshold is imposed during the test phase. The metric must exist in the source and be preserved. A Toutiao search result that overlaps the official board is Level 1.

### Level 3: Potential Topic

A topic is Level 3 when it is relevant but lacks official hot-list or numeric heat evidence. This includes:

- Toutiao keyword-search results that have only search position and no public heat metric.
- Results discovered through Baidu Qianfan web search.

Potential topics are separate from formal recommendations.

## Fact Status

Heat evidence and factual evidence are independent.

Each result records one of:

- `verified`: supported by an official, original, or corroborated source.
- `unverified`: hot or relevant, but no sufficient factual confirmation was found.
- `disputed`: credible sources conflict.
- `debunked`: reliably proven false.

Unverified and disputed topics may still be displayed, but their uncertainty must be stated. Debunked topics are excluded. The system must not rewrite an unverified claim as an established fact.

## Time Window and Business Day

All timestamps use Asia/Shanghai time.

- Platform searches and Qianfan fallback results are limited to the most recent 24 hours.
- Content older than 24 hours is excluded unless the source supplies new heat evidence within the window.
- A platform snapshot older than 24 hours cannot provide Level 1 evidence.
- The operational business day begins at 08:00, not at midnight.

Before 08:00, a user request returns the user's most recent generated result and exposes its actual date. If no historical result exists, the generation layer returns `not_ready` with no content. Viewing an old result before 08:00 does not consume that day's generation opportunity.

## Collection Workflow

The manual daily collection command performs these stages:

1. Collect all five hot lists independently.
2. Save raw responses before normalization.
3. Normalize all valid records.
4. Save collection status for each platform.
5. Collect all available detail text.
6. Write detail completion status without failing the entire run for individual item failures.

Platform failures are isolated. Toutiao, Baidu, and Juejin continue if a Cookie-backed platform fails.

When scheduling is added later, the intended start time is 08:00. A platform collection failure will retry after ten minutes, up to three attempts. The last successful snapshot may be retained for diagnostics, but snapshots older than 24 hours cannot prove Level 1 heat.

## Detail Collection

An expected daily snapshot is approximately 230 to 250 items:

- Toutiao: about 50
- Baidu Hot Search: about 51
- Juejin: about 40
- Weibo: about 50
- Zhihu: about 50

Toutiao and Juejin use small concurrency, initially three workers per platform, and collect their details in one run.

Weibo and Zhihu use independent low-concurrency queues:

- Five items per batch.
- At most two concurrent requests per platform.
- Roughly eight to ten minutes between batches with small random jitter.
- The target completion time for a future scheduled run is 09:30. A run that finishes by 10:00 is still considered within the normal operating window.

If a user generation request needs a Weibo or Zhihu item whose detail is still pending, that item enters a priority queue. It is fetched immediately, cached, and skipped by the later background batch. If priority detail collection fails, the result uses the available summary.

Baidu Hot Search uses the explanation embedded in the board. If an explanation is absent, the title becomes the TXT detail fallback and the structured content status is `title_only`. Baidu items may use `platform_not_provided` for publication time; collection time must never be presented as publication time.

No extractor may invent or expand missing article text. Detail fallbacks use only source-provided summaries or titles.

## User Recommendation Generation

Generation is lazy and limited to once per user per business day.

On a user's first eligible request:

1. Return an existing result if one already exists for the user and business date.
2. Read the normalized daily snapshots and detail cache.
3. Match titles, summaries, and details using `primary_keyword`.
4. Preserve each platform's official board order.
5. Search Toutiao once with `primary_keyword` and fetch details for new results.
6. Classify the matched records into Levels 1, 2, and 3.
7. Generate the output files atomically.

No cross-platform sorting or deduplication is performed. Within a platform, Level 1 records retain official order. Level 2 records follow in source-return order. Each record displays its level.

### No-Match Fallback

If there are no personalized Level 1 or Level 2 results:

1. Show up to five reliable general hot-list records.
2. Default to the top three Toutiao records and top two Baidu Hot Search records.
3. If one primary platform lacks enough data, fill from the other primary platform.
4. Do not force five records if both sources contain fewer valid items.
5. Call Qianfan once and add up to five Level 3 potential topics.

General hot-list records must be labeled as non-personalized fallback content.

## Qianfan Fallback

Use the Baidu Qianfan web search API:

```text
POST https://qianfan.baidubce.com/v2/ai_search/web_search
```

Credentials are read from:

```text
QIANFAN_API_KEY
QIANFAN_SECRET_KEY
```

The fallback makes at most one call per user per business day. It builds one short query from the saved profile, for example:

```text
{primary_keyword} {secondary_track} {persona核心受众} 最新热点
```

The request returns at most ten web results and filters for the most recent 24 hours. The generator retains at most five relevant results. It uses the raw web-search references rather than a generated summary so every result remains traceable and can produce an independent TXT file.

Qianfan failure does not prevent the general hot-list fallback or completion of other outputs.

## Storage Layout

Test-phase data is retained indefinitely.

```text
data/
├── daily_hot_lists/
│   └── 2026-07-13/
│       ├── normalized/
│       │   ├── toutiao.json
│       │   ├── baidu.json
│       │   ├── juejin.json
│       │   ├── weibo.json
│       │   └── zhihu.json
│       ├── raw/
│       │   ├── toutiao.json
│       │   ├── baidu.html
│       │   ├── juejin.json
│       │   ├── weibo.html
│       │   └── zhihu.json
│       ├── details/
│       │   └── <platform>_<sequence>.txt
│       └── collection_status.json
├── user_profiles/
│   └── user_001.json
└── user_results/
    └── user_001/
        └── 2026-07-13/
            ├── report.md
            ├── result.json
            └── topics/
                └── <platform>_<sequence>.txt
```

Raw responses are diagnostic artifacts and never drive user matching directly. Normalized JSON is the machine-readable source for recommendation generation.

Each topic TXT is deliberately simple:

```text
标题：
平台：
热点等级：
发布时间：
采集时间：

详细内容：
```

When full text is unavailable, the detailed content field contains only the source-provided summary or title. The JSON records whether the content is `full_text`, `summary`, or `title_only`.

## Integration Contract

The current project exposes:

- A Python function for downstream direct integration.
- A CLI command for manual collection, generation, and testing.
- The stable filesystem outputs described above.

The generation result includes one of these statuses:

- `existing`: the user already has a result for the business day.
- `generated`: a new result was generated successfully.
- `no_result`: generation completed but produced no usable content.
- `not_ready`: the request occurred before 08:00 and no historical result exists.
- `failed`: generation failed.

Concurrent requests for the same user and business day must share one generation operation. Successful output is written atomically so downstream consumers never observe a partially written result directory.

## Error Handling

- Platform and item failures are isolated and recorded in status metadata.
- Missing or invalid Cookies do not stop non-Cookie platforms.
- Detail failures fall back to summary or title.
- Qianfan failures skip potential topics without failing formal recommendations.
- Failed partial output is written to a temporary location and never mistaken for a completed user result.
- Secrets and Cookies are never written to raw captures, result JSON, TXT files, logs, or version control.

## Verification

The first complete manual run must verify:

1. Raw and normalized snapshots exist for every successful platform.
2. Approximately expected record counts are collected without assuming an exact count.
3. Detail TXT files exist for every normalized record, including fallback content where necessary.
4. Cookie-backed failures do not block other platforms.
5. `primary_keyword` matching produces platform-grouped results in the fixed order.
6. Toutiao search results receive the correct level based on board overlap and numeric evidence.
7. Qianfan is called no more than once and returns no more than five potential topics.
8. The no-match path returns up to three Toutiao and two Baidu general-hot records plus up to five potential topics.
9. Markdown, JSON, and topic TXT outputs agree.
10. A repeated same-day generation request returns `existing` without repeating collection or search calls.
11. TXT files contain only the six approved fields and never contain invented content.
