# Toutiao Keyword Search Design

## Purpose

Toutiao should use the user's profile keywords to actively search for related hot content, instead of relying only on the global Toutiao hot board and then matching afterward.

The goal is to improve relevance while preserving the V3 requirement that final topics should have a usable heat signal.

## Current Problem

The current Toutiao workflow collects the global hot board from:

```text
https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
```

This gives clear `HotValue` metrics, but it is too broad. For a technical profile such as `tech_ai_creator`, the global hot board can return zero matches even though Toutiao may have relevant search results for profile keywords.

## Design

The Toutiao workflow will become query-driven:

1. Load `UserProfile`.
2. Build `TopicQuery` records.
3. Expand each query into Toutiao search phrases.
4. Fetch Toutiao search results for each phrase.
5. Parse the returned JSON `dom` HTML fragment.
6. Normalize search rows into `HotItem`.
7. Keep the global hot board as a supplemental source for overlap and heat validation.
8. Match and deduplicate results.
9. Fetch details where possible, otherwise keep search summary or hot board payload.
10. Write all standard output files plus `search_results.json` and `hot_board_items.json`.

## Search Source

Use the Toutiao search endpoint:

```text
https://so.toutiao.com/search/?keyword={keyword}&pd=information&source=search_subtab_switch&from=information&format=json&count=10&offset=0
```

Observed behavior:

- The endpoint returns JSON.
- Search results are embedded inside the `dom` field as HTML.
- Chinese keywords return useful results.
- English technical keywords can return zero results, so query expansion is required.

## Query Expansion

The first version will use deterministic expansion only:

- Original `TopicQuery.query`.
- Each individual keyword in `TopicQuery.keywords`.
- Simple platform-specific Chinese aliases for known technical terms:
  - `AI Agent` -> `AI智能体`
  - `Claude Code` -> `Claude Code AI编程`
  - `MCP` -> `MCP 协议`
  - `Cursor` -> `Cursor AI编程`

The query expansion function should be easy to extend in future versions, but should not call an LLM in this version.

## Heat Signal Rules

Toutiao search results may not expose the same `HotValue` as the global hot board. Use this order:

1. If a search result overlaps with the global hot board, use the global hot board `HotValue`.
2. If the search result HTML includes numeric heat, reading, comment, or discussion text, parse that into `HeatMetrics.metrics`.
3. If no numeric heat exists, use search rank as a weak heat signal:
   - `heat.metric_name = "search_rank"`
   - `heat.value = count - rank + 1`
   - `raw_payload["heat_signal_strength"] = "weak"`

The human report should make weak heat visible.

## Output Layout

Keep the existing platform layout:

```text
outputs/
  {profile_id}/
    toutiao/
      run_{YYYYMMDD_HHMMSS}/
        profile.json
        queries.json
        hot_board_items.json
        search_results.json
        hot_items.json
        matches.json
        item_details.json
        report.md
```

`hot_items.json` is the final merged candidate list used for matching and reporting.

## Detail Behavior

Keep the current detail strategy:

1. Fetch item URL.
2. Try static HTML article extraction.
3. If extraction fails, fall back to search result summary or hot board payload.

Browser/session extraction is out of scope for this version.

## Testing Requirements

Add tests for:

- Query expansion.
- Search response parsing from `dom`.
- Search result normalization into `HotItem`.
- Merging search results with hot board overlap.
- Pipeline output includes `search_results.json` and `hot_board_items.json`.
- Existing global hot board behavior still works as supplemental data.

## Acceptance Criteria

- `uv run pytest -q` passes.
- `python -m heated_topics_v3.cli toutiao --profile config\profiles\tech_ai_creator.json --output-root outputs` writes all standard files plus `search_results.json` and `hot_board_items.json`.
- Toutiao can return profile-related candidates even when the global hot board has zero direct matches.
- The report distinguishes strong heat signals from weak search-rank signals.
