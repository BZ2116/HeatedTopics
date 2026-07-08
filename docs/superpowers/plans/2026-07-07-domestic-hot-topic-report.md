# Domestic Hot Topic Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `topic_analysis.md` as a domestic hot topic matching report with recommendation tables, evidence tables, caution sections, and keyword hit statistics.

**Architecture:** Keep `analysis.py` as the deterministic structured analysis layer and `analysis_render.py` as the Markdown formatting layer. Add only renderer-facing fields that can be derived from existing `CandidateTopic`, `SearchResult`, and `EnrichedContent` data.

**Tech Stack:** Python dataclasses, pytest, existing `src.search_discovery` package.

## Global Constraints

- Focus on domestic hot messages and Chinese search/news sources.
- Keep the existing `topic_analysis.json` and `topic_analysis.md` flow.
- Do not add a new external API in this change.
- Do not change provider fetching behavior.
- Do not treat model output as factual evidence.

---

### Task 1: Analysis Fields For Domestic Report

**Files:**
- Modify: `src/search_discovery/analysis.py`
- Test: `tests/search_discovery/test_analysis.py`

**Interfaces:**
- Consumes: `CandidateTopic`, `SearchResult`, `EnrichedContent`
- Produces: topic row keys `verification_summary`, `suggested_titles`, and enriched evidence rows with `source_type`, `source_name`

- [ ] **Step 1: Write failing tests**

Add assertions that a topic row includes:

```python
assert row["verification_summary"]["source_count"] == 2
assert row["verification_summary"]["has_clear_publish_time"] is True
assert row["verification_summary"]["risk_label"] == "低"
assert row["suggested_titles"]
assert row["evidence"][0]["source_type"]
assert row["evidence"][0]["source_name"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/search_discovery/test_analysis.py -q`
Expected: FAIL because the new fields are not present.

- [ ] **Step 3: Write minimal implementation**

Add deterministic helpers in `analysis.py`:

```python
def _verification_summary(topic, evidence): ...
def _suggested_titles(topic): ...
def _source_type(source_id, content_type): ...
def _source_name(source_id): ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/search_discovery/test_analysis.py -q`
Expected: PASS.

### Task 2: Domestic Markdown Renderer

**Files:**
- Modify: `src/search_discovery/analysis_render.py`
- Test: `tests/search_discovery/test_analysis_render.py`

**Interfaces:**
- Consumes: existing analysis dict plus Task 1 fields
- Produces: Markdown sections `国内热点匹配报告`, `一、本轮结论`, `二、优先推荐选题`, `三、话题详情`, `四、需要谨慎处理的话题`, `五、证据与来源统计`, `六、关键词命中情况`

- [ ] **Step 1: Write failing tests**

Assert the rendered Markdown contains the new section headings, a recommendation table, evidence table headers, caution section, and keyword hit table.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/search_discovery/test_analysis_render.py -q`
Expected: FAIL because current renderer uses the older report format.

- [ ] **Step 3: Write minimal implementation**

Replace the renderer layout while preserving model suggestion preference for topic prose.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/search_discovery/test_analysis_render.py -q`
Expected: PASS.

### Task 3: Focused Verification

**Files:**
- No code changes unless tests reveal a defect.

- [ ] **Step 1: Run search discovery tests touched by this change**

Run: `uv run pytest tests/search_discovery/test_analysis.py tests/search_discovery/test_analysis_render.py -q`
Expected: PASS.

- [ ] **Step 2: Review diff**

Run: `git diff -- src/search_discovery/analysis.py src/search_discovery/analysis_render.py tests/search_discovery/test_analysis.py tests/search_discovery/test_analysis_render.py docs/superpowers/specs/2026-07-07-domestic-hot-topic-report-design.md docs/superpowers/plans/2026-07-07-domestic-hot-topic-report.md`
Expected: only report-format related changes.
