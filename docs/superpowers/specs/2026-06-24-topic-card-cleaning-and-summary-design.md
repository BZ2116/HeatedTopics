# Topic Card Cleaning And Summary Design

## Goal

Improve the creator topic cards so they are easier to read, less polluted by raw page noise, and ready for either manual or model-generated summaries.

This design extends the creator topic classification index. It does not replace the existing hot-topic collection or classification flow.

## Problems To Solve

1. The current card layout exposes internal fields but does not read like a creator-facing brief.
2. Some `detail` content contains page chrome, sidebars, navigation text, ads, duplicate hot-list blocks, and raw URLs.
3. Rule-generated summaries are too generic.
4. Future model summaries should be possible without making every normal run depend on an API call.

## Design Direction

Use a three-layer content pipeline:

1. `raw_content`: original collected text, preserved for audit and debugging.
2. `clean_content`: deterministic local cleanup result, used by classification and display.
3. `summary`: structured creator-facing summary, selected from manual, model, or rule output.

The first implementation should prioritize deterministic cleaning and a better card shape. Model summaries should be optional and cacheable.

## Output Shape

Each topic should keep existing classification fields and add a richer `card` shape:

```json
{
  "title": "河北高考分数线",
  "domain_path": ["教育升学", "高考", "分数线"],
  "content_modes": ["数据整理", "实时跟进"],
  "audience_tags": ["学生", "家长"],
  "card": {
    "source_platforms": ["weibo"],
    "hotness_label": "排名 1；微博热度 1624096",
    "raw_content_preview": "NEW 1 搜索结果 综合...",
    "clean_content": "河北高考分数线公布：本科批历史科目组合485分，物理科目组合443分...",
    "summary": {
      "mode": "rule",
      "what_happened": "河北公布 2026 年高考分数线。",
      "why_it_matters": "考生和家长需要据此判断志愿填报策略。",
      "creator_angle": "适合做分数线汇总、志愿填报提醒和本地教育解读。",
      "tracking_hint": "后续可追踪志愿填报时间、各批次录取线和考生反馈。"
    },
    "manual_summary": null,
    "model_summary": null,
    "risk_note": "教育信息需核对官方来源。",
    "evidence_urls": []
  }
}
```

## Summary Priority

Card rendering should use this priority:

```text
manual_summary > model_summary > summary(rule) > clean_content excerpt
```

`manual_summary` and `model_summary` should use the same internal shape as `summary`:

```json
{
  "mode": "manual",
  "what_happened": "...",
  "why_it_matters": "...",
  "creator_angle": "...",
  "tracking_hint": "..."
}
```

This makes the renderer simple and lets downstream consumers compare or override summary sources.

## Card Layout

Markdown cards should be organized for a creator, not for pipeline debugging.

Recommended layout:

```markdown
### 河北高考分数线

热度与平台：排名 1；微博热度 1624096；来源 weibo
分类与受众：教育升学 > 高考 > 分数线；学生、家长
适合创作：数据整理、实时跟进

一句话：河北公布 2026 年高考分数线。

具体内容：
河北高考分数线公布：本科批历史科目组合485分，物理科目组合443分...

创作者角度：
适合做分数线汇总、志愿填报提醒和本地教育解读。

可追踪点：
后续可追踪志愿填报时间、各批次录取线和考生反馈。

风险提示：
教育信息需核对官方来源。

证据链接：
- https://...
```

The card should not show raw page chrome by default. Raw excerpts can stay in JSON for audit.

## Cleaning Layer

Create a deterministic cleaning layer before summary generation.

Responsibilities:

- Remove common page chrome:
  - `搜索结果`, `综合`, `实时`, `用户`, `视频`, `图片`, `高级搜索`
  - `登录`, `关注`, `广告`, `展开c`, `下一页`
  - repeated footer/customer-service text
- Remove obvious duplicate hot-list blocks when they are unrelated to the current title.
- Collapse repeated whitespace and excessive blank lines.
- Preserve important facts, numbers, dates, named entities, and URLs in evidence fields.
- Limit `clean_content` length for display, while preserving raw content separately.

Cleaning should be rule-based and testable. It should not call a model.

## Summary Modes

### Rule Summary

Default mode. Always available.

Inputs:

- title
- domain path
- content modes
- audience tags
- clean content
- traceability
- risk level

Output:

- `what_happened`
- `why_it_matters`
- `creator_angle`
- `tracking_hint`

Rule summaries can use templates plus extracted facts. They should be conservative and avoid inventing details.

### Manual Summary

Optional mode. Useful for important topics before model integration.

Suggested input file:

`data/manual/topic_summaries.json`

Shape:

```json
{
  "河北高考分数线": {
    "what_happened": "...",
    "why_it_matters": "...",
    "creator_angle": "...",
    "tracking_hint": "..."
  }
}
```

Manual summaries override model and rule summaries.

### Model Summary

Optional mode. Not required for normal runs.

Recommended command shape:

```powershell
uv run python -m src.core_pipeline.run build-creator-topic-index --render-report --summary-mode model
```

or a separate enrichment command:

```powershell
uv run python -m src.core_pipeline.run enrich-topic-summaries --provider openai
```

The model should only consume already cleaned and classified topic data:

- title
- domain path
- platform/hotness
- clean content
- evidence URLs
- risk level

The model should not consume full raw pages by default.

Model output should be cached to avoid repeated API cost:

`data/cache/summaries/`

## Recommended Placement

Add focused modules:

- `src/core_pipeline/topic_content_cleaner.py`
  - `clean_topic_content(title, raw_text) -> CleanedContent`
  - deterministic cleanup and display truncation

- `src/core_pipeline/topic_summary.py`
  - `generate_rule_summary(topic, clean_content) -> dict`
  - `select_display_summary(card) -> dict`
  - later: `load_manual_summaries(path)` and model adapter hooks

Keep `creator_topic_classifier.py` responsible for classification and assembling the final index, but delegate cleaning and summaries to these modules.

## Error Handling

- If `clean_content` is empty, fall back to title and hot-list metadata.
- If manual summary JSON is missing or invalid, continue with rule summaries and emit a warning.
- If model summary fails, keep rule summary and mark `model_summary` as null.
- If raw text looks garbled, preserve it in `raw_content_preview` and set lower summary confidence.

## Tests

Add tests for:

- removing known page chrome while preserving factual lines
- avoiding unrelated sidebar contamination
- rule summary fields for a high-confidence education topic
- summary priority: manual before model before rule
- card renderer uses structured summary fields
- missing manual/model summary does not break report generation

## Rollout

First implementation:

1. Add deterministic cleaner.
2. Add rule summary generator.
3. Update card JSON shape.
4. Update Markdown renderer.
5. Regenerate `creator_topic_index.json` and `creator_topic_cards.md`.

Second implementation:

1. Add manual summary loader.
2. Add optional model summary adapter.
3. Add summary cache.

This keeps the immediate card quality work independent from API configuration and cost.
