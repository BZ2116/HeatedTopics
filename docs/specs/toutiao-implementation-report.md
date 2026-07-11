# Toutiao Implementation Report

## Status

Toutiao collection is now query-driven. It searches Toutiao with phrases derived from the user profile, then uses the global hot board as supplemental heat validation.

Current command:

```powershell
cd E:\.code\My\heatedTopics-V3
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli toutiao --profile config\profiles\tech_ai_creator.json --output-root outputs
```

## Primary Source: Keyword Search

The primary source is Toutiao search:

```text
https://so.toutiao.com/search/?keyword={keyword}&pd=information&source=search_subtab_switch&from=information&format=json&count=10&offset=0
```

Observed behavior:

- The endpoint returns JSON.
- Search results are embedded in the `dom` HTML field.
- Chinese keywords return useful results more reliably than English technical terms.
- English technical terms need deterministic Chinese aliases.

The workflow expands profile queries before searching:

- Original query, such as `AI Agent MCP`.
- Individual keywords, such as `AI Agent` and `MCP`.
- Known Toutiao aliases, such as `AI智能体`, `MCP 协议`, and `Claude Code AI编程`.

## Supplemental Source: Global Hot Board

The supplemental source remains the Toutiao PC hot board JSON endpoint:

```text
https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
```

The endpoint returns `HotValue`, which is the strongest available heat metric.

The mobile endpoint that appears in public references returned an empty list in live testing, so the implementation uses the PC hot board endpoint.

## Normalization

Search rows are normalized into `HotItem`:

- `platform`: `toutiao`
- `item_type`: `search_result`
- `item_id`: `toutiao_search_{article_id_or_rank}`
- `title`: parsed result title
- `url`: parsed result URL
- `rank`: search result order
- `summary`: parsed nearby result text
- `category`: `search`
- `raw_payload["source_kind"]`: `search_result`

Hot board rows are normalized into `HotItem`:

- `platform`: `toutiao`
- `item_type`: `topic`
- `item_id`: `toutiao_{ClusterId}`
- `heat.metric_name`: `hot_value`
- `heat.value`: parsed `HotValue`

Merged rows use `source_kind = search_hot_board_overlap` when a search result URL overlaps the hot board. In that case, the merged item keeps the search title/summary but uses the hot board `HotValue`.

## Heat Signal Rules

Toutiao search results do not always expose `HotValue`. The implementation uses this order:

1. Hot board overlap: `hot_value`, strong heat.
2. Search DOM includes `热度`: `search_heat`, medium heat.
3. Search DOM includes `阅读` or `评论`: `search_engagement`, medium heat.
4. No numeric signal: `search_rank`, weak heat.

The report prints both source and heat signal so weak results are visible.

## Detail Strategy

The detail workflow follows the project standard:

1. Fetch the item URL.
2. Try to extract text from an HTML `<article>` block.
3. Remove `style` and `script` content while extracting text.
4. If no article body can be extracted, fall back to search summary or hot board payload.

Current live behavior:

- Trending pages usually do not expose article body text in public static HTML.
- Article pages currently return JavaScript-heavy shell HTML with no static article body.
- Therefore live detail extraction often falls back to `toutiao_hot_board_payload`.

Full detail extraction may require browser automation or an authenticated/session-supported strategy.

## Output Layout

Toutiao follows the same simplified profile/source/run layout as Juejin:

```text
outputs/
  {profile_id}/
    toutiao/
      run_{YYYYMMDD_HHMMSS}/
        hot_items.json
        article_texts/
          001_{title}.txt
        report.md
```

`hot_items.json` is the final matched/query-derived candidate list used for reporting. Raw search results and raw hot board rows are used internally but are not written as separate run files.

`article_texts/*.txt` stores one plain-text file per matched article. Images are intentionally ignored.

Latest smoke-test output:

```text
outputs/tech_ai_creator/toutiao/run_20260711_152000/
```

Latest smoke-test result:

- `hot_items.json`: 8 records.
- `article_texts/*.txt`: 8 records.
- `report.md`: 1 report.

All 8 matches in the latest smoke test used `search_keyword_hit` with `search_rank` weak heat. This confirms the keyword-driven flow runs end to end, but also shows that the current public search JSON often exposes result existence more reliably than detailed ranking metrics.

## Follow-Up Decision

Before investing more in Toutiao detail extraction, confirm whether to add browser/session-supported collection.

If yes, the next version should:

- Use browser automation for item pages.
- Wait for article content to render.
- Extract rendered article text.
- Keep keyword search as the primary relevance source.
- Keep the hot board endpoint as the strongest heat validation source.
