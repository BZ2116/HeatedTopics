# Toutiao Implementation Report

## Status

Toutiao hot-list collection is implemented as the second platform workflow after Juejin.

Current command:

```powershell
cd E:\.code\My\heatedTopics-V3
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli toutiao --profile config\profiles\tech_ai_creator.json --output-root outputs
```

## Hot List Source

The current source is the Toutiao PC hot board JSON endpoint:

```text
https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
```

The endpoint returns a JSON payload with:

- `data`: hot-list rows.
- `Title`: topic title.
- `Url`: topic, article, live, or external URL.
- `HotValue`: platform heat value.
- `QueryWord`: search/topic phrase.
- `InterestCategory`: optional category tags.

The mobile endpoint that appears in public references currently returns an empty list in live testing, so this implementation uses the PC hot board endpoint.

## Normalization

Each row is normalized into `HotItem`:

- `platform`: `toutiao`
- `item_type`: `topic`
- `item_id`: `toutiao_{ClusterId}`
- `title`: `Title`
- `url`: `Url`
- `rank`: source order
- `heat.metric_name`: `hot_value`
- `heat.value`: parsed `HotValue`
- `summary`: `QueryWord` when present, otherwise `Title`
- `category`: first `InterestCategory` when present, otherwise `Label`

## Detail Strategy

The detail workflow follows the project standard:

1. Fetch the item URL.
2. Try to extract text from an HTML `<article>` block.
3. Remove `style` and `script` content while extracting text.
4. If no article body can be extracted, fall back to the hot board payload.

Current live behavior:

- Trending pages usually do not expose article body text in public static HTML.
- Article pages currently return JavaScript-heavy shell HTML with no static article body.
- Therefore live detail extraction currently falls back to `toutiao_hot_board_payload`.

This means Toutiao currently satisfies:

- Clear heat metrics.
- Hot-list title/topic data.
- Stable structured hot-list dataset.

But Toutiao does not yet fully satisfy:

- Detailed article body content through simple HTTP fetching.

Full detail extraction may require browser automation or an authenticated/session-supported strategy.

## Output Layout

Toutiao follows the same layout as Juejin:

```text
outputs/
  {profile_id}/
    toutiao/
      run_{YYYYMMDD_HHMMSS}/
        profile.json
        queries.json
        hot_items.json
        matches.json
        item_details.json
        report.md
```

Latest smoke-test output:

```text
outputs/tech_ai_creator/toutiao/run_20260711_145000/
```

Latest smoke-test result:

- `hot_items.json`: 50 records.
- `matches.json`: 0 records for the current `tech_ai_creator` profile and current Toutiao hot board.
- `item_details.json`: 0 records because there were no matched items.

Provider-level live detail probes:

- Trending URL detail extraction fell back to `toutiao_hot_board_payload`.
- Article URL detail extraction also fell back to `toutiao_hot_board_payload`.

## Follow-Up Decision

Before investing more in Toutiao detail extraction, confirm whether to add browser/session-supported collection.

If yes, the next version should:

- Use browser automation for item pages.
- Wait for article content to render.
- Extract rendered article text.
- Keep the current hot-list JSON endpoint as the source of rank and heat metrics.

