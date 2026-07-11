# Platform Hot Topic Workflow Standard

This document records the Juejin implementation as the baseline workflow for all later platform hot topic collectors.

## Goal

For each user profile, collect platform hot topics that have both:

- Clear heat metrics.
- Enough detail for human review and downstream topic reuse.

Each platform workflow must output two product surfaces:

- A human-readable report.
- A structured dataset for downstream projects.

## Baseline Flow

Use the same flow for every platform unless a platform limitation makes one step impossible:

1. Load one `UserProfile`.
2. Build `TopicQuery` records from the profile.
3. Collect the platform hot list without requiring a query when the platform supports a general hot list.
4. Normalize every hot list row into `HotItem`.
5. Match `HotItem` records against `TopicQuery`.
6. Fetch detailed information for matched items.
7. Normalize details into `ItemDetail`.
8. Write matched hot items, article text files, and report under the user profile output directory.
9. Render a human-readable report.

The user profile is still converted into queries even when the source itself does not require a query. Queries are used for matching, scoring, report context, and later cross-platform clustering.

## Output Layout

Every platform run writes under:

```text
outputs/
  {profile_id}/
    {source_id}/
      run_{YYYYMMDD_HHMMSS}/
        hot_items.json
        article_texts/
          001_{title}.txt
        report.md
```

Example:

```text
outputs/
  tech_ai_creator/
    juejin/
      run_20260711_132853/
        hot_items.json
        article_texts/
          001_AI Agent workflow with MCP.txt
        report.md
```

`hot_items.json` contains only the matched or query-derived hot items for the profile. It does not store every raw platform hot-list row.

Article body text is written into `article_texts/*.txt`, one file per matched article. Images are intentionally ignored in this version.

## Required Data Objects

Each platform adapter should produce these objects:

- `UserProfile`: the user or creator profile used as the minimum output unit.
- `TopicQuery`: profile-derived query and matching intent.
- `HotItem`: one ranked hot-list item with heat metrics.
- `MatchResult`: one matched hot item and the query terms that matched it.
- `ItemDetail`: full or enriched detail for one matched item.

Later cross-platform aggregation can add `TopicCluster`, but individual platform collectors should not depend on clustering.

## Juejin Baseline

Current command:

```powershell
cd E:\.code\My\heatedTopics-V3
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli juejin --profile config\profiles\tech_ai_creator.json --output-root outputs
```

Current implementation:

- Hot list endpoint: `https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot`
- Detail strategy A: request Juejin article detail JSON API.
- Detail strategy B: if the JSON API fails or returns no content, fetch the article page and extract article text from HTML.

Observed live behavior:

- Hot list collection works.
- The public detail JSON API currently returns an error for the simple `article_id` request shape.
- The article page fallback works and can extract usable article body text.
- The fallback parser must remove `style` and `script` content to avoid CSS or page state leaking into article content.

Current output rule:

- `hot_items.json`: matched Juejin records only, enriched with match metadata and article text file path.
- `article_texts/*.txt`: one text file per matched Juejin article.
- `report.md`: human-readable summary.

## Platform Adapter Checklist

For every new platform, confirm and document:

- `source_id`: stable lowercase identifier, such as `bilibili`, `baidu`, or `weibo`.
- Hot-list entry point: API, public page, RSS, sitemap, or other source.
- Heat metrics: rank, hot score, views, likes, comments, shares, favorites, or platform-specific equivalent.
- Detail entry point: JSON detail API first when available, page crawl fallback when needed.
- Required headers, cookies, tokens, or browser/session support.
- Rate limit and anti-bot risk.
- Whether the source supports keyword search, general hot list collection, or both.
- Whether the source can be collected without login.

## Standard Decision Rule

Use this decision order for each platform:

1. Prefer stable public JSON APIs.
2. If no stable API exists, use public HTML pages.
3. If public HTML is incomplete because content renders dynamically, use browser automation.
4. If login, cookies, captcha, or app-only signatures are required, mark the platform as needing extra tool support before implementation.

## When To Ask For Confirmation

Ask before proceeding when any of these are true:

- The platform requires login cookies or a real browser session.
- The only available data source may violate platform terms or requires aggressive anti-bot bypassing.
- The heat metric is ambiguous or not comparable across items.
- The platform returns only titles with no detail path.
- The platform has multiple competing hot lists and the intended list is unclear.
- The output schema needs a new field that affects downstream consumers.

## Implementation Requirements

Each platform implementation should include:

- Provider tests for hot-list parsing.
- Provider tests for detail extraction, including API success and fallback behavior when applicable.
- Pipeline tests for output layout and required files.
- One CLI command that runs the whole flow for a user profile.
- A live smoke test recorded in the platform report or implementation notes.
