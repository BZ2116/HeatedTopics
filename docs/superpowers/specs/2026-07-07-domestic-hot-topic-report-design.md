# Domestic Hot Topic Report Design

## Goal

Improve the final Markdown output for keyword-driven domestic hot topic discovery. The report should help a user quickly decide which domestic news or trend topics are worth turning into content, which topics need caution, and which sources support each recommendation.

## Scope

- Focus on domestic hot messages and Chinese search/news sources.
- Keep the existing `topic_analysis.json` and `topic_analysis.md` flow.
- Do not add a new external API in this change.
- Do not change provider fetching behavior.
- Do not treat model output as factual evidence.

## Report Shape

The Markdown report should use this structure:

1. `# 国内热点匹配报告`
2. Metadata: generated time, keyword coverage, search scope.
3. `## 一、本轮结论`
4. `## 二、优先推荐选题`
5. `## 三、话题详情`
6. `## 四、需要谨慎处理的话题`
7. `## 五、证据与来源统计`
8. `## 六、关键词命中情况`

## Topic Detail Requirements

Each topic detail should include:

- Recommended level.
- Topic score.
- Matched keywords.
- Suitable content directions.
- Topic summary.
- Why it matters.
- Creator angles.
- Evidence source table.
- Verification notes.
- Suggested titles.

## Verification Requirements

The report must make evidence quality visible:

- Single-source topics should be called out.
- Topics without clear published time should be called out.
- Medium or high risk topics should include cautious wording guidance.
- Evidence rows should include source type, source name, title, time, and confidence when available.

## Implementation Notes

- Add deterministic fields in `analysis.py` where the renderer needs structured data.
- Keep `analysis_render.py` responsible for Markdown formatting only.
- Preserve model synthesis preference for prose summaries, but do not allow model output to overwrite source metadata or verification metrics.
