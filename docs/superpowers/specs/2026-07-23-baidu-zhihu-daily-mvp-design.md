# Baidu Hot Search and Zhihu Daily MVP Design

## Goal

Add two anonymous, cookie-free providers to the cached hot-content workflow:

- Baidu Hot Search, where an official hot event supplies rank and `hotScore`
  while a separately attributed supporting article supplies full text.
- Zhihu Daily, where the latest and archived official recommendations supply
  rank evidence and the public story detail API supplies full text.

Both providers must support the existing user flow:

1. Read the daily qualified cache.
2. Match the user's primary keyword locally.
3. Stop when at least 5 qualified results match.
4. Otherwise search or scan the platform's public discovery surface.
5. Inspect no more than 60 unique candidates.
6. Return no more than 20 qualified results.

No title, summary, generated text, login-only content, or incomplete page is
allowed to stand in for full text.

## Scope

### Included

- Provider implementations named `baidu_hot` and `zhihu_daily`.
- Daily hot-list or recommendation collection.
- Full-text retrieval and validation.
- Conditional keyword discovery when cached matches are below 5.
- Stable caching through the existing raw, normalized, eligible, rejected,
  detail, active-snapshot, and search-cache repositories.
- CLI registration in the existing cached-news commands.
- Fixture-based contract tests and anonymous live smoke validation.

### Excluded

- Baidu account login, Baidu commercial APIs, Qianfan credentials, or persistent
  Cookies.
- Zhihu question hot lists, answers, login state, or general Zhihu search.
- Browser rendering or CAPTCHA bypass.
- Semantic embedding or LLM-based event linking.
- Cross-platform deduplication or scoring.
- Generating Xiaohongshu posts. These providers only supply qualified source
  material for the later recommendation layer.

## Implementation Approach

The implementation ports the relevant DailyHotApi parsing ideas into native
Python providers and calls the original public endpoints directly. It does not
depend on a public DailyHotApi deployment and does not introduce a second
service.

This approach is preferred over:

1. Calling the public DailyHotApi instance, which would still require a
   separate body and search layer and would create an avoidable runtime
   dependency.
2. Forking and deploying DailyHotApi as another service, which would add
   infrastructure beyond the needs of this two-provider MVP.

The feature is implemented on branch
`feature/baidu-zhihu-daily-mvp`, based on committed cached-news workflow state
`2aeca86`.

## Shared Provider Contract

Both providers implement the existing `NewsProvider` protocol:

```python
platform: str
weights: Mapping[str, float]
absolute_floors: Mapping[str, float]

collect_hot_list(collected_at: str) -> ProviderCapture
fetch_detail(item: HotItem, collected_at: str) -> ItemDetail
search(
    keyword: str,
    page: int,
    page_size: int,
    collected_at: str,
) -> ProviderCapture
enrich_metrics(
    items: Sequence[HotItem],
    collected_at: str,
) -> tuple[HotItem, ...]
```

The shared collection and discovery layers gain four optional capabilities
without changing
the required methods of existing providers:

```python
search_with_context(
    keyword: str,
    page: int,
    page_size: int,
    collected_at: str,
    official_articles: Sequence[QualifiedArticle],
) -> ProviderCapture

build_board_evidence(
    item: HotItem,
    floors: Mapping[str, float],
) -> HeatEvidence | None

build_search_evidence(
    item: HotItem,
    floors: Mapping[str, float],
) -> HeatEvidence | None

rank_articles(
    articles: Sequence[QualifiedArticle],
) -> tuple[QualifiedArticle, ...]
```

The discovery orchestrator calls `search_with_context` when present and
otherwise calls the existing `search`. Daily collection calls
`build_board_evidence` when present and otherwise retains the existing
official-board metric behavior. Discovery calls `build_search_evidence` when
present and otherwise retains the existing public-metric threshold behavior.
Both stages call `rank_articles` when present and otherwise retain
`rank_platform_articles`.

These hooks are needed because:

- Baidu search articles inherit official evidence from a cached parent event.
- Zhihu Daily's latest list qualifies through positive official rank even
  though it has no engagement metric.
- Zhihu Daily archive results have official recommendation evidence but no
  engagement metrics.
- Zhihu Daily must sort by recommendation date before within-day rank.

Existing Sina, The Paper, and NetEase providers do not implement the optional
hooks and therefore retain their current behavior.

The shared workflow continues to enforce:

- `MIN_RESULTS = 5`
- `MAX_RESULTS = 20`
- `SEARCH_PAGE_SIZE = 15`
- `MAX_SEARCH_CANDIDATES = 60`
- native structured or known-container body minimum of 80 effective characters
- at least 2 real paragraphs or 3 complete sentences
- no summary or title fallback
- platform-isolated failures and sanitized error codes

## Baidu Hot Search

### Official Board

Request:

```text
GET https://top.baidu.com/board?tab=realtime
```

The provider extracts the JSON object embedded in:

```html
<!--s-data:...-->
```

It accepts both observed envelopes:

```text
data.cards[0].content
cards[0].content
```

If the first content item contains another `content` list, that nested list is
used. HTTP errors, missing `s-data`, malformed JSON, an unrecognized envelope,
an empty board, or a board containing no valid records fail closed.

### Normalized Event

Each valid event becomes a `HotItem` with:

```text
platform          = "baidu_hot"
item_id           = stable digest of the normalized event query
title             = word or title
summary           = desc
rank              = official list position
heat.value        = hotScore
heat.metric_name  = "hot_score"
heat.metrics      = {"hot_score": hotScore}
url               = Baidu event/search URL
raw_payload       = original row plus rawUrl, image, query, and event URL
```

The item ID is derived from the normalized query rather than the list index, so
rank changes do not invalidate the same-day detail cache.

### Supporting Article and Full Text

A Baidu event is not itself an article. `fetch_detail` therefore resolves one
supporting article:

1. Try an article-like public `rawUrl` from the board row.
2. If it is absent, still points to a search/topic page, or fails full-text
   validation, search Baidu for the exact event title.
3. Resolve public result redirects.
4. Inspect results in returned order until one candidate:
   - has an HTTP(S) URL;
   - is not a Baidu search, login, video-only, image-only, or aggregation page;
   - is explicitly related to the event by normalized title/query terms; and
   - yields accepted full text.
5. Store the supporting article URL in `ItemDetail.source_url`.

The `HotItem.url` remains the Baidu event URL. The final record therefore keeps
event heat provenance separate from article content provenance.

Full text is extracted in this order:

1. JSON-LD `articleBody` or recognized structured article state.
2. Known article containers supported by the shared content extractor.
3. GNE fallback.
4. Existing full-text validation.

GNE content must satisfy the existing stricter 200-character fallback minimum.

### User Search

When fewer than 5 cached Baidu event packages match the user's keyword:

1. Select current qualified hot-event packages that match the normalized user
   keyword across event title, event summary, or cached supporting body.
2. Search the selected event titles, not arbitrary unrelated keywords.
3. For each result, require both event-title relevance and user-keyword
   relevance across result title, summary, and accepted body.
4. Reuse the parent event's official rank and `hotScore` as event heat evidence.
5. Deduplicate by resolved article URL, then stable item ID.
6. Reject results that cannot be tied to a current hot event.

`search_with_context` receives only the cached qualified articles already read
by the discovery workflow. It must not refresh the Baidu board during a user
request.

If no current event matches the keyword, Baidu discovery returns an explicit
empty result. Ordinary Baidu search results cannot enter the formal pool
without current official hot-event evidence.

One hot event may contribute multiple distinct supporting articles during
conditional search. Every returned record identifies the same parent event in
`raw_payload` and preserves the actual article URL in its detail. Its search
item ID combines the parent event digest with a digest of the resolved article
URL, so multiple articles for one event do not collide in storage or
deduplication.

### Ranking

Baidu uses:

```text
weights = {"hot_score": 1.0}
```

Official rank remains a deterministic tie-breaker. Search result order never
becomes heat.

## Zhihu Daily

### Latest Recommendation Board

Request:

```text
GET https://daily.zhihu.com/api/4/news/latest
```

Only stories with `type == 0` are retained. HTTP errors, malformed JSON, a
missing stories list, an empty response, or no valid type-0 stories fail
closed.

Each story becomes:

```text
platform          = "zhihu_daily"
item_id           = "zhihu_daily_<story_id>"
title             = story title
summary           = story hint when present
rank              = official position in the response
heat.value        = None
heat.metric_name  = "official_rank"
heat.metrics      = {}
url               = public story URL
raw_payload       = original story plus recommendation date
```

No synthetic reading, like, comment, or popularity number is created. A
positive official rank and the `official_hot_board` marker are sufficient heat
evidence under the existing contract. `build_board_evidence` supplies that
evidence and prevents the generic public-metric guard from rejecting an
otherwise valid official recommendation.

### Story Detail

Request:

```text
GET https://daily.zhihu.com/api/4/news/<story_id>
```

The detail response must be a JSON object containing a nonempty HTML `body`.
The provider:

1. Removes scripts, styles, navigation, recommendation widgets, and page chrome.
2. Preserves paragraph boundaries from the story body.
3. Uses the detail `share_url` as `ItemDetail.source_url` when valid, otherwise
   the normalized story URL.
4. Returns `full_text` only after native-content validation succeeds.

Missing, short, summary-equivalent, malformed, or rejected content never enters
the eligible cache.

### Seven-Day Archive Search

Zhihu Daily does not expose a native keyword search API. Its MVP search is a
bounded scan of public official archives:

```text
GET https://daily.zhihu.com/api/4/news/before/YYYYMMDD
```

Search behavior:

1. Scan at most the 7 calendar days preceding the current latest response.
2. Preserve each story's recommendation date and its rank within that archive
   response.
3. Deduplicate by story ID.
4. Stop after 60 unique candidates.
5. Use title and hint as a cheap keyword prefilter.
6. Fetch detail for prefiltered candidates and confirm the normalized keyword
   against title, hint, or accepted full text.
7. Return no more than 20 qualified stories.

Archive responses are official recommendation lists, so their date and
within-day rank are valid official recommendation evidence. They are not
reported as numeric user engagement.

`build_search_evidence` constructs `official_hot_board` evidence from the
archive date and positive within-day rank, bypassing the public-engagement
metric floor without weakening the behavior of other providers.

### Ranking

Zhihu Daily has no numeric public engagement field. Results therefore sort
deterministically by:

1. official recommendation identity;
2. recommendation date, newest first;
3. within-day official rank, ascending;
4. publication time, newest first when available;
5. stable story ID.

This provider-specific ordering is used instead of inventing a numeric heat
metric. `rank_articles` implements the ordering for both cached and archive
results.

## Storage and Cache Behavior

The feature reuses the existing layout:

```text
data/daily_hot_lists/<business-date>/
├── raw/<platform>.json-or-html
├── normalized/<platform>.json
├── eligible/<platform>.json
├── rejected/<platform>.json
├── details/<platform>_<stable-item-id>.txt
└── collection_status.json

data/search_cache/<business-date>/<platform>/<keyword-hash>/
├── eligible.json
├── rejected.json
└── status.json
```

Daily collection fetches each latest board once and prefetches all candidate
details. User requests read the qualified daily cache and do not refresh the
official board.

Search failures use the existing short negative cache. A failed request is
never persisted as a successful empty response. The last successful active
snapshot may be reused within the existing 48-hour window.

## CLI Integration

The existing cached-news CLI commands remain the only new operational surface:

```text
heated-topics collect-news
heated-topics generate-news
```

Provider registration is extended to include:

```text
baidu_hot
zhihu_daily
```

No separate Baidu- or Zhihu-specific CLI command is introduced.

## Failure Handling

Both providers:

- call `raise_for_status()` before parsing;
- reject malformed success envelopes and ambiguous empty results;
- use bounded request timeouts;
- do not persist response headers, Cookies, tokens, or exception messages;
- sanitize collection status to exception class or fixed reason code;
- fail independently from every other provider;
- do not invoke Playwright or retry through a login flow.

Baidu-specific failures include:

- missing or malformed `s-data`;
- CAPTCHA or verification pages;
- redirect loops;
- no event-linked supporting article;
- body extraction failures.

Zhihu-specific failures include:

- missing `stories`;
- unsupported story type;
- missing detail `body`;
- archive date or envelope mismatch;
- body validation failures.

An individual detail failure rejects that item but does not discard other
qualified items from the same platform.

## Testing

### Provider Contract Tests

Baidu fixtures cover:

- both known board envelopes;
- `hotScore`, rank, description, image, query, and stable-ID mapping;
- malformed and empty boards;
- direct supporting article success;
- search fallback and redirect resolution;
- event/article relevance rejection;
- full-text validation and source attribution;
- no current hot-event evidence.

Zhihu Daily fixtures cover:

- latest list parsing and type filtering;
- detail body extraction and paragraph preservation;
- malformed and empty latest responses;
- missing or invalid detail body;
- seven-day archive ordering and deduplication;
- 60-candidate and 20-result bounds;
- full-text keyword matching;
- official date/rank evidence.

### Workflow Tests

- Both platforms participate in daily collection independently.
- Qualified and rejected records are persisted correctly.
- Five cached matches skip search.
- Fewer than five matches trigger the correct provider discovery.
- Search cache success, empty, and failure states behave truthfully.
- Existing Toutiao, Juejin, Sina, The Paper, and NetEase behavior remains
  unchanged.

### Verification

Before completion:

1. Run focused provider and workflow tests.
2. Run the complete test suite.
3. Compile all Python source and tests.
4. Run `git diff --check`.
5. Perform an anonymous live smoke collection and one keyword search per new
   provider.
6. Record counts, rejection reasons, endpoint limitations, and credential scan
   results without committing large real article bodies.

## Acceptance Criteria

The MVP is complete only when:

1. A real anonymous Baidu board yields ranked events with positive `hotScore`.
2. At least one real Baidu event is paired with an accepted, separately
   attributed supporting article body.
3. Baidu conditional search returns only articles tied to current hot events.
4. A real anonymous Zhihu Daily latest response yields official recommendations.
5. Zhihu Daily detail responses yield accepted full text.
6. Seven-day archive discovery can find a keyword match and preserve archive
   date/rank evidence.
7. Neither provider needs a persistent Cookie, login, browser, or secret.
8. Empty, malformed, partial, or unauthenticated responses fail closed.
9. All automated tests and the anonymous smoke verification pass.
