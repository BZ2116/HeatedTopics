# V3 Platform Hot List Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a V3 platform hot-list matrix that collects hot topics from the first batch of stable platforms, then expands to the second batch after the first report proves the flow.

**Architecture:** Keep platform ordering in `src/core_pipeline/source_registry.py`, add V3-specific collector modules under `src/core_pipeline/v3_hot_matrix/`, and render a standalone Markdown report under `reports/v3/`. Each provider returns normalized records and structured feasibility status so blocked platforms do not break the run.

**Tech Stack:** Python standard library, existing `pytest` test suite, existing `uv run pytest` workflow, existing project package layout under `src/core_pipeline/`.

## Global Constraints

- First batch platforms are exactly `juejin`, `bilibili`, `baidu`.
- Second batch platforms are exactly `weibo`, `toutiao`, `zhihu`.
- `xiaohongshu` is excluded because another project already handles it.
- Search engines are not the primary V3 discovery source.
- Providers must preserve raw payloads for debugging.
- Providers must return structured failure statuses instead of breaking the full run.
- Do not implement captcha bypass, account evasion, fingerprint tricks, proxy rotation, or aggressive scraping of login-protected pages.

---

## File Structure

- Modify: `src/core_pipeline/source_registry.py`
  Stores V3 platform batches, flattened order, and excluded-platform reasons.
- Modify: `tests/core_pipeline/test_source_registry.py`
  Locks the V3 platform list and order.
- Create: `src/core_pipeline/v3_hot_matrix/types.py`
  Defines normalized V3 hot topic and provider result data structures.
- Create: `src/core_pipeline/v3_hot_matrix/providers.py`
  Implements first-batch providers for Juejin, Bilibili, and Baidu.
- Create: `src/core_pipeline/v3_hot_matrix/run.py`
  Orchestrates provider collection, output writing, and report rendering.
- Create: `src/core_pipeline/v3_hot_matrix/render.py`
  Renders `reports/v3/platform_hot_list_matrix.md`.
- Create: `tests/core_pipeline/v3_hot_matrix/test_types.py`
  Tests normalized record behavior.
- Create: `tests/core_pipeline/v3_hot_matrix/test_providers.py`
  Tests provider extraction using fixtures or sample payloads.
- Create: `tests/core_pipeline/v3_hot_matrix/test_render.py`
  Tests Markdown report structure.

### Task 1: V3 Platform Registry

**Files:**
- Modify: `src/core_pipeline/source_registry.py`
- Modify: `tests/core_pipeline/test_source_registry.py`
- Modify: `docs/superpowers/specs/2026-07-11-v3-platform-hot-list-matrix-design.md`

**Interfaces:**
- Produces: `V3_PLATFORM_BATCHES: dict[str, tuple[str, ...]]`
- Produces: `V3_PLATFORM_ORDER: tuple[str, ...]`
- Produces: `V3_EXCLUDED_PLATFORMS: dict[str, str]`

- [x] **Step 1: Write the failing test**

```python
def test_v3_platform_batches_follow_stability_first_order(self):
    assert V3_PLATFORM_BATCHES == {
        "stable_interface_first": ("juejin", "bilibili", "baidu"),
        "secondary_public_hot_lists": ("weibo", "toutiao", "zhihu"),
    }
    assert V3_PLATFORM_ORDER == (
        "juejin",
        "bilibili",
        "baidu",
        "weibo",
        "toutiao",
        "zhihu",
    )
    assert V3_EXCLUDED_PLATFORMS == {
        "xiaohongshu": "handled_by_external_project",
    }
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core_pipeline/test_source_registry.py::SourceRegistryTests::test_v3_platform_batches_follow_stability_first_order -q`

Expected: FAIL during import because `V3_EXCLUDED_PLATFORMS` is not defined.

- [x] **Step 3: Write minimal implementation**

```python
V3_PLATFORM_BATCHES = {
    "stable_interface_first": ("juejin", "bilibili", "baidu"),
    "secondary_public_hot_lists": ("weibo", "toutiao", "zhihu"),
}

V3_PLATFORM_ORDER = tuple(
    platform
    for batch in V3_PLATFORM_BATCHES.values()
    for platform in batch
)

V3_EXCLUDED_PLATFORMS = {
    "xiaohongshu": "handled_by_external_project",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core_pipeline/test_source_registry.py::SourceRegistryTests::test_v3_platform_batches_follow_stability_first_order -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core_pipeline/source_registry.py tests/core_pipeline/test_source_registry.py docs/superpowers/specs/2026-07-11-v3-platform-hot-list-matrix-design.md docs/superpowers/plans/2026-07-11-v3-platform-hot-list-matrix.md
git commit -m "feat: define V3 platform collection order"
```

### Task 2: V3 Normalized Types

**Files:**
- Create: `src/core_pipeline/v3_hot_matrix/__init__.py`
- Create: `src/core_pipeline/v3_hot_matrix/types.py`
- Create: `tests/core_pipeline/v3_hot_matrix/test_types.py`

**Interfaces:**
- Consumes: `V3_PLATFORM_ORDER`
- Produces: `V3HotTopic`
- Produces: `V3ProviderResult`
- Produces: `normalize_heat_value(value: object) -> int | None`

- [ ] **Step 1: Write the failing test**

```python
from src.core_pipeline.v3_hot_matrix.types import V3HotTopic, V3ProviderResult, normalize_heat_value


def test_normalize_heat_value_accepts_common_display_forms():
    assert normalize_heat_value("12345") == 12345
    assert normalize_heat_value("12.3万") == 123000
    assert normalize_heat_value("热度 8,765") == 8765
    assert normalize_heat_value("") is None


def test_provider_result_preserves_raw_payload_and_status():
    topic = V3HotTopic(
        platform="baidu",
        source_name="百度热搜",
        title="测试热点",
        rank=1,
        heat_value=123,
        heat_label="123",
        url="https://top.baidu.com/",
        summary="",
        category="realtime",
        collected_at="2026-07-11T00:00:00+08:00",
        fetch_status="success",
        raw_payload={"title": "测试热点"},
    )
    result = V3ProviderResult(
        platform="baidu",
        fetch_status="success",
        rating="A",
        topics=[topic],
        message="ok",
    )
    assert result.topics[0].raw_payload["title"] == "测试热点"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_types.py -q`

Expected: FAIL because `src.core_pipeline.v3_hot_matrix.types` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement frozen dataclasses for `V3HotTopic` and `V3ProviderResult`, plus a conservative heat parser for plain numbers, comma numbers, and Chinese `万`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_types.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core_pipeline/v3_hot_matrix tests/core_pipeline/v3_hot_matrix/test_types.py
git commit -m "feat: add V3 hot matrix data types"
```

### Task 3: First-Batch Provider Extraction

**Files:**
- Create: `src/core_pipeline/v3_hot_matrix/providers.py`
- Create: `tests/core_pipeline/v3_hot_matrix/test_providers.py`

**Interfaces:**
- Consumes: `V3HotTopic`
- Produces: `collect_first_batch(fetcher: Callable[[str], str | bytes], collected_at: str) -> list[V3ProviderResult]`

- [ ] **Step 1: Write the failing test**

```python
from src.core_pipeline.v3_hot_matrix.providers import collect_first_batch


def test_collect_first_batch_returns_stability_first_platforms():
    def fake_fetcher(url):
        if "juejin" in url:
            return '{"data":[{"title":"AI 开发工具","hot":321,"url":"https://juejin.cn/post/1"}]}'
        if "bilibili" in url:
            return '{"data":{"list":[{"title":"热门视频","stat":{"view":1200},"short_link_v2":"https://b23.tv/1"}]}}'
        if "baidu" in url:
            return '{"cards":[{"content":[{"word":"百度热点","hotScore":"456","url":"https://top.baidu.com/"}]}]}'
        return "{}"

    results = collect_first_batch(fake_fetcher, "2026-07-11T00:00:00+08:00")

    assert [result.platform for result in results] == ["juejin", "bilibili", "baidu"]
    assert all(result.fetch_status in {"success", "partial", "empty_result"} for result in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_providers.py -q`

Expected: FAIL because `collect_first_batch` is not defined.

- [ ] **Step 3: Write minimal implementation**

Implement provider functions using injected `fetcher` so tests do not hit live websites. Each provider should convert available fields into `V3HotTopic` and return `empty_result` when no rows are found.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_providers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core_pipeline/v3_hot_matrix/providers.py tests/core_pipeline/v3_hot_matrix/test_providers.py
git commit -m "feat: add V3 first batch providers"
```

### Task 4: V3 Report Rendering

**Files:**
- Create: `src/core_pipeline/v3_hot_matrix/render.py`
- Create: `tests/core_pipeline/v3_hot_matrix/test_render.py`

**Interfaces:**
- Consumes: `list[V3ProviderResult]`
- Produces: `render_platform_hot_list_matrix(results: list[V3ProviderResult], generated_at: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
from src.core_pipeline.v3_hot_matrix.render import render_platform_hot_list_matrix
from src.core_pipeline.v3_hot_matrix.types import V3ProviderResult


def test_render_platform_hot_list_matrix_includes_batches_and_exclusions():
    report = render_platform_hot_list_matrix(
        [
            V3ProviderResult(
                platform="baidu",
                fetch_status="success",
                rating="A",
                topics=[],
                message="ok",
            )
        ],
        "2026-07-11T00:00:00+08:00",
    )

    assert "# V3 平台热榜矩阵报告" in report
    assert "第一批" in report
    assert "juejin, bilibili, baidu" in report
    assert "小红书" in report
    assert "handled_by_external_project" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_render.py -q`

Expected: FAIL because `render_platform_hot_list_matrix` is not defined.

- [ ] **Step 3: Write minimal implementation**

Render metadata, platform feasibility table, first-batch topics, second-batch pending list, and excluded-platform reasons.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_render.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core_pipeline/v3_hot_matrix/render.py tests/core_pipeline/v3_hot_matrix/test_render.py
git commit -m "feat: render V3 platform hot matrix report"
```

### Task 5: V3 CLI Smoke Run

**Files:**
- Create: `src/core_pipeline/v3_hot_matrix/run.py`
- Create: `tests/core_pipeline/v3_hot_matrix/test_run.py`

**Interfaces:**
- Consumes: `collect_first_batch`
- Consumes: `render_platform_hot_list_matrix`
- Produces: `run_v3_hot_matrix(output_root: Path, report_root: Path, collected_at: str | None = None) -> dict[str, Path]`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from src.core_pipeline.v3_hot_matrix.run import run_v3_hot_matrix


def test_run_v3_hot_matrix_writes_expected_outputs(tmp_path: Path):
    outputs = run_v3_hot_matrix(
        output_root=tmp_path / "data",
        report_root=tmp_path / "reports",
        collected_at="2026-07-11T00:00:00+08:00",
    )

    assert outputs["raw"].exists()
    assert outputs["processed"].exists()
    assert outputs["feasibility"].exists()
    assert outputs["report"].exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_run.py -q`

Expected: FAIL because `run_v3_hot_matrix` is not defined.

- [ ] **Step 3: Write minimal implementation**

Use provider results to write:

- `data/v3/raw/platform_hot_lists.jsonl`
- `data/v3/processed/platform_hot_topics.json`
- `data/v3/processed/platform_feasibility.json`
- `reports/v3/platform_hot_list_matrix.md`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core_pipeline/v3_hot_matrix/test_run.py -q`

Expected: PASS.

- [ ] **Step 5: Run focused V3 test suite**

Run: `uv run pytest tests/core_pipeline/test_source_registry.py tests/core_pipeline/v3_hot_matrix -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/core_pipeline/v3_hot_matrix tests/core_pipeline/v3_hot_matrix
git commit -m "feat: add V3 hot matrix smoke run"
```
