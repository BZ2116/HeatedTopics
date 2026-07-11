# V3 Platform Hot List Matrix Design

## Goal

V3 changes the discovery strategy from broad search-engine discovery to a focused platform hot-list matrix. The first version should collect hot topics directly from a small set of high-value platforms, normalize the results, and produce a feasibility summary that shows which platforms are stable enough for long-term automation.

The goal is not to solve every platform detail problem at once. The goal is to run a practical test and answer four questions:

1. Which major platforms can provide useful hot topic records today?
2. Which fields can be collected reliably from each platform?
3. Which platforms need login state, browser automation, third-party APIs, or manual support?
4. Which collected topics are useful enough for creator topic selection?

## Background

The previous search-driven path can find related pages, but search results are noisy and usually do not expose clear heat metrics. Search is still useful for background evidence, but it is a weak primary signal for deciding whether a topic is hot.

V3 treats platform hot lists as the primary source of heat. Popular platforms already rank content using user behavior such as searches, views, comments, shares, likes, and publishing velocity. Their hot lists are therefore better first-layer signals than generic search result pages.

## Recommended Approach

Use a platform-by-platform hot-list collector.

The collector should target known websites first, collect the visible hot topics, normalize them into one shared structure, and then generate a platform feasibility report. Search engines and general web search APIs remain out of the V3 primary path.

Initial target platforms:

| Platform | Priority | Expected Value | Initial Feasibility |
| --- | --- | --- | --- |
| Juejin | First batch | Tech, AI, developer topics | Medium to high; stable interface direction |
| Bilibili | First batch | Video culture, youth topics, entertainment, tech videos | Medium to high; rankings and video metrics are useful |
| Baidu Hot Search | First batch | General public search demand | High; suitable as a baseline source |
| Weibo | High | Public events, entertainment, society, fast-moving public discussion | Medium; hot list can be collected, richer details may need login state |
| Toutiao | High | News, public events, social topics | Medium; hot list or public pages need verification |
| Zhihu | Medium | Question-led public discussion and knowledge topics | Medium; useful but topic meaning may require detail reading |

Xiaohongshu is intentionally excluded from V3 collection in this project because another project already handles it.

## Platform Batches

V3 collection order:

1. First batch: `juejin`, `bilibili`, `baidu`.
2. Second batch: `weibo`, `toutiao`, `zhihu`.
3. Excluded: `xiaohongshu`, because it is handled by an external project.

## Alternatives Considered

### Option A: Continue Search-Driven Discovery

This keeps the current search provider path as the main discovery mechanism. It is flexible, but the results are too noisy and heat is inferred rather than observed.

Use this only for detail enrichment and fact checking.

### Option B: Use Only Third-Party Aggregated APIs

This is fast and stable when the API is good. However, it hides platform-specific constraints and can make the project dependent on one commercial provider.

Use this as a fallback or supplement, not the only V3 path.

### Option C: Build Platform Hot-List Providers Directly

This is the recommended V3 path. It gives the project direct visibility into what each platform can and cannot provide. It also creates a concrete feasibility report before the team invests in heavier automation.

The tradeoff is that each platform needs a small adapter and its own failure handling.

## V3 Scope

V3 includes:

- Collect hot-list records from selected platforms.
- Normalize records into a shared topic structure.
- Preserve raw payloads for later debugging.
- Mark platform feasibility and collection limitations.
- Generate a readable test report.
- Keep collection frequency low and cache-friendly.
- Avoid captcha bypass, account evasion, fingerprint tricks, proxy rotation, or other platform-rule avoidance.

V3 does not include:

- Full post or note detail collection for every platform.
- A complete creator recommendation engine rewrite.
- Paid data provider integration unless it is later selected deliberately.
- Search-engine-driven topic discovery as the main source.
- Aggressive scraping of login-protected pages.
- Xiaohongshu collection in this project.

## Data Model

Every platform provider should produce a normalized `HotTopic`-like record:

| Field | Meaning |
| --- | --- |
| `platform` | Source platform, such as `juejin`, `bilibili`, `baidu`, `weibo`, `toutiao`, `zhihu` |
| `source_name` | Human-readable source name |
| `title` | Hot topic title |
| `rank` | Current rank when available |
| `heat_value` | Platform-provided heat, view count, score, or display metric when available |
| `heat_label` | Raw heat text when the platform uses display labels |
| `url` | Source URL or topic URL |
| `summary` | Short description, if available |
| `category` | Platform section or route, if available |
| `collected_at` | Collection timestamp |
| `fetch_status` | `success`, `partial`, `blocked`, `login_required`, `rate_limited`, or `failed` |
| `raw_payload` | Original platform payload or extracted row |

Provider-specific fields can stay in `raw_payload` until they prove useful enough to promote into the shared model.

## Feasibility Rating

Each platform should receive one rating after a test run:

| Rating | Meaning |
| --- | --- |
| A | Stable API or simple public endpoint. Suitable for scheduled collection. |
| B | Public webpage collection works, but selectors and page changes need monitoring. |
| C | Useful data exists, but collection depends on login state or browser automation. |
| D | Collection is unstable, heavily blocked, or requires external tooling or paid provider support. |

The report should explain the reason for the rating, not only the letter.

## Collection Flow

```text
platform provider list
-> collect records from each provider
-> normalize hot topic fields
-> save raw records
-> save normalized records
-> cluster duplicate topics across platforms
-> score basic usefulness
-> render feasibility and topic summary report
```

The first V3 test can run once manually. Scheduled execution should wait until the first feasibility report shows which providers are stable.

## Output Files

Suggested outputs:

| Path | Content |
| --- | --- |
| `data/v3/raw/platform_hot_lists.jsonl` | Raw provider records, one JSON object per row |
| `data/v3/processed/platform_hot_topics.json` | Normalized hot topic records |
| `data/v3/processed/platform_feasibility.json` | Provider status, fields collected, and rating |
| `reports/v3/platform_hot_list_matrix.md` | Human-readable V3 test report |

The exact paths can be adjusted to match existing project layout, but V3 outputs should stay separate from existing V2 search-discovery outputs during the test.

## Report Shape

The V3 report should include:

1. Run metadata: time, platforms, record counts.
2. Platform feasibility table.
3. Top collected topics by platform.
4. Cross-platform repeated topics.
5. Useful topics for creator follow-up.
6. Topics that are too vague or lack context.
7. Platforms that need login, browser automation, third-party API, or manual support.
8. Recommended next implementation step.

## Basic Topic Usefulness Rules

A topic is more useful when:

- It has a clear entity, event, product, person, policy, or conflict.
- It has a rank or heat metric.
- It appears on more than one platform.
- It has a source URL.
- It belongs to a target domain such as tech, AI, finance, education, consumer, local life, entertainment, or public affairs.

A topic is less useful when:

- It is only a vague phrase.
- It has no heat signal and no source URL.
- It is purely clickbait without context.
- It requires sensitive claims but lacks authoritative sources.
- It cannot be collected repeatedly without login or blocking.

## Error Handling

Each provider should return a structured failure instead of breaking the full run. The run should continue when one platform fails.

Expected failure statuses:

- `login_required`: page requires account state.
- `captcha_required`: page asks for captcha or human verification.
- `rate_limited`: provider blocks frequent access.
- `selector_changed`: page loaded but expected content could not be extracted.
- `network_error`: request failed.
- `empty_result`: request succeeded but no topic rows were found.

## Testing Strategy

The first implementation should use small, focused tests:

- Unit tests for normalizing provider records.
- Fixture tests for HTML or JSON payload extraction.
- CLI smoke test that runs the V3 matrix collector with a small platform list.
- Report rendering test that verifies platform feasibility and topic rows appear.

Live collection should be treated as an integration smoke test because platform pages can change.

## Success Criteria

V3 is successful when one manual run can produce:

- At least three platforms with usable records.
- A normalized topic file.
- A feasibility file that explains platform limitations.
- A Markdown report that makes it obvious which platforms are worth continuing.
- A clear list of platforms that require browser/login/third-party support.

V3 does not need to solve every blocked platform. A blocked or partially available platform is still useful if the report records that limitation clearly.

## Recommended First Implementation Slice

Start with the smallest useful provider set:

1. Juejin hot list as tech vertical signal.
2. Bilibili ranking as content heat signal.
3. Baidu hot search as baseline.

After this slice produces a report, add Weibo, Toutiao, and Zhihu as the second batch.

## Open Decisions For Review

1. Whether cross-platform topic scoring should be included in V3 test output or deferred until stable collection is confirmed.
2. Whether Toutiao should be collected directly from public pages or through an aggregator if the public page proves unstable.
