# Hot Topic Detail Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable recent-hot-topic detail collection flow: collect today's or the last 7 days' hot topics, deduplicate them, collect non-empty detail evidence for each topic, and render JSON plus Markdown outputs.

**Architecture:** Reuse the existing `src/core_pipeline` foundation instead of rebuilding schemas. DailyHotApi remains the discovery layer, `DetailEvidence` remains the detail-storage unit, and the new flow adds window-aware topic collection plus detail evidence collection that treats title-only records as incomplete. The first version is still a manual, file-based pipeline; analysis, trust scoring, advanced query planning, and skill/agent packaging stay out of scope.

**Tech Stack:** Python standard library, existing `unittest` test suite, existing `Makefile`, DailyHotApi HTTP JSON, optional browser/session details for Weibo and Xiaohongshu, JSON files, Markdown reports.

---

## 0. Product Rule

This plan is successful only when the generated outputs distinguish between:

- a hot topic title discovered from a hot list;
- detail evidence with non-empty `content`;
- failed or blocked detail collection with explicit `fetch_status` and `error_type`.

DailyHotApi title, rank, and heat alone are not valid topic details.

## 1. File Structure

Create:

- `src/core_pipeline/recent_topics.py`: collection-window parsing, lightweight topic-key normalization, and hot-record deduplication.
- `src/core_pipeline/detail_collector.py`: topic-level detail collection orchestration that produces `DetailEvidence` rows from search results and provider status.
- `tests/core_pipeline/test_recent_topics.py`: tests for `today` / `last_7_days` window handling and deduplication.
- `tests/core_pipeline/test_detail_collector.py`: tests proving detail collection produces non-empty evidence when search snippets exist and explicit failure rows when they do not.

Modify:

- `src/core_pipeline/dailyhot_client.py`: add a route collector that turns configured DailyHotApi routes into `HotRecord` rows and records failed routes as non-throwing failures.
- `src/core_pipeline/providers/baidu.py`: add deterministic query generation and multi-query search-result conversion while keeping current `collect_baidu_detail` behavior compatible.
- `src/core_pipeline/report_renderer.py`: render the first-version `recent_hot_topics_digest.md` with hot-list sources, detail snippets, and detail status.
- `src/core_pipeline/run.py`: add `collect-recent-details --window today|last_7_days` and wire collection, deduplication, detail evidence writing, clustering, brief generation, and report rendering.
- `Makefile`: add `collect-recent-hot-details`.
- `tests/core_pipeline/test_dailyhot_client.py`: cover route collection failure behavior.
- `tests/core_pipeline/test_report_renderer.py`: cover the new report fields.
- `tests/core_pipeline/test_run.py`: cover output paths and CLI orchestration using injected fixture data.

Generated runtime files:

- `data/raw/dailyhot_records.json`
- `data/processed/topic_clusters.json`
- `data/evidence/detail_evidence.json`
- `data/processed/topic_briefs.json`
- `reports/recent_hot_topics_digest.md`

## 2. Task 1: Recent Topic Window And Deduplication

**Files:**

- Create: `src/core_pipeline/recent_topics.py`
- Create: `tests/core_pipeline/test_recent_topics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/core_pipeline/test_recent_topics.py`:

```python
import unittest

from src.core_pipeline.recent_topics import (
    collection_window_days,
    deduplicate_hot_records,
    normalize_topic_key,
)
from src.core_pipeline.types import HotRecord


def hot_record(record_id: str, platform: str, title: str, rank: int = 1) -> HotRecord:
    return HotRecord(
        id=record_id,
        source="dailyhotapi",
        platform=platform,
        route=platform,
        category="core_discovery",
        title=title,
        rank=rank,
        hot_value="100",
        url=f"https://example.com/{record_id}",
        mobile_url="",
        desc="",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-22T20:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )


class RecentTopicsTests(unittest.TestCase):
    def test_collection_window_days_accepts_supported_windows(self):
        self.assertEqual(collection_window_days("today"), 1)
        self.assertEqual(collection_window_days("last_7_days"), 7)

    def test_collection_window_days_rejects_unknown_window(self):
        with self.assertRaises(ValueError):
            collection_window_days("month")

    def test_normalize_topic_key_removes_hot_list_noise(self):
        self.assertEqual(normalize_topic_key("  某事件 爆！ "), "某事件")
        self.assertEqual(normalize_topic_key("某事件 热"), "某事件")

    def test_deduplicate_hot_records_keeps_all_source_ids(self):
        records = [
            hot_record("hot_weibo_001", "weibo", "某事件 爆", rank=1),
            hot_record("hot_baidu_003", "baidu", "某事件", rank=3),
            hot_record("hot_zhihu_001", "zhihu", "另一个话题", rank=1),
        ]

        topics = deduplicate_hot_records(records)

        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["topic_key"], "某事件")
        self.assertEqual(topics[0]["hot_record_ids"], ["hot_weibo_001", "hot_baidu_003"])
        self.assertEqual(topics[0]["platforms"], ["baidu", "weibo"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_recent_topics -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.core_pipeline.recent_topics'`.

- [ ] **Step 3: Implement recent topic helpers**

Create `src/core_pipeline/recent_topics.py`:

```python
import re
from typing import Any

from src.core_pipeline.types import HotRecord


SUPPORTED_WINDOWS = {
    "today": 1,
    "last_7_days": 7,
}

HOT_LIST_DECORATIONS = ("热", "爆", "新", "荐", "沸")


def collection_window_days(window: str) -> int:
    if window not in SUPPORTED_WINDOWS:
        supported = ", ".join(sorted(SUPPORTED_WINDOWS))
        raise ValueError(f"Unsupported collection window {window!r}; expected one of: {supported}")
    return SUPPORTED_WINDOWS[window]


def normalize_topic_key(title: str) -> str:
    normalized = str(title).strip().lower()
    normalized = re.sub(r"[!！?？#＃【】\[\]（）()：:，,。.\s]+", "", normalized)
    changed = True
    while changed:
        changed = False
        for suffix in HOT_LIST_DECORATIONS:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
    return normalized


def deduplicate_hot_records(records: list[HotRecord]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        topic_key = normalize_topic_key(record.title)
        if not topic_key:
            continue
        bucket = buckets.setdefault(
            topic_key,
            {
                "topic_key": topic_key,
                "canonical_title": record.title.strip(),
                "hot_record_ids": [],
                "platforms": set(),
                "records": [],
                "best_rank": record.rank,
            },
        )
        bucket["hot_record_ids"].append(record.id)
        bucket["platforms"].add(record.platform)
        bucket["records"].append(record)
        bucket["best_rank"] = min(bucket["best_rank"], record.rank)
        if record.rank == bucket["best_rank"]:
            bucket["canonical_title"] = record.title.strip()
    topics = []
    for bucket in buckets.values():
        topics.append(
            {
                "topic_key": bucket["topic_key"],
                "canonical_title": bucket["canonical_title"],
                "hot_record_ids": bucket["hot_record_ids"],
                "platforms": sorted(bucket["platforms"]),
                "best_rank": bucket["best_rank"],
                "records": bucket["records"],
            }
        )
    return sorted(topics, key=lambda topic: (topic["best_rank"], topic["canonical_title"]))
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_recent_topics -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/core_pipeline/recent_topics.py tests/core_pipeline/test_recent_topics.py
git commit -m "feat: add recent topic deduplication"
```

Expected: commit succeeds.

## 3. Task 2: DailyHot Route Collection

**Files:**

- Modify: `src/core_pipeline/dailyhot_client.py`
- Modify: `tests/core_pipeline/test_dailyhot_client.py`

- [ ] **Step 1: Add failing DailyHot collection tests**

Append to `tests/core_pipeline/test_dailyhot_client.py`:

```python
from src.core_pipeline.dailyhot_client import collect_dailyhot_records


class DailyHotCollectionTests(unittest.TestCase):
    def test_collect_dailyhot_records_collects_multiple_routes(self):
        payloads = {
            "weibo": {"data": [{"title": "微博热点", "hot": "100"}]},
            "baidu": {"data": [{"title": "百度热点", "hot": "90"}]},
        }

        def fetcher(route: str):
            return payloads[route]

        records = collect_dailyhot_records(
            routes=("weibo", "baidu"),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=fetcher,
        )

        self.assertEqual([record.title for record in records], ["微博热点", "百度热点"])

    def test_collect_dailyhot_records_records_route_failures(self):
        def fetcher(route: str):
            raise RuntimeError("network down")

        records = collect_dailyhot_records(
            routes=("weibo",),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=fetcher,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id, "hot_weibo_failed")
        self.assertEqual(records[0].fetch_status, "failed")
        self.assertEqual(records[0].error_type, "RuntimeError")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_dailyhot_client -v
```

Expected: FAIL because `collect_dailyhot_records` is not defined.

- [ ] **Step 3: Implement route collection**

Append to `src/core_pipeline/dailyhot_client.py`:

```python
from collections.abc import Callable


def collect_dailyhot_records(
    routes: tuple[str, ...],
    captured_at: str,
    fetcher: Callable[[str], dict[str, Any]],
) -> list[HotRecord]:
    records: list[HotRecord] = []
    for route in routes:
        try:
            payload = fetcher(route)
            records.extend(normalize_dailyhot_response(route, payload, captured_at))
        except Exception as exc:
            records.append(
                HotRecord(
                    id=f"hot_{route}_failed",
                    source="dailyhotapi",
                    platform=route,
                    route=route,
                    category=route_role(route),
                    title=f"{route} route failed",
                    rank=0,
                    hot_value="",
                    url="",
                    mobile_url="",
                    desc="",
                    author="",
                    cover="",
                    timestamp="",
                    captured_at=captured_at,
                    raw_payload={},
                    fetch_status="failed",
                    error_type=type(exc).__name__,
                )
            )
    return records
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_dailyhot_client -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/core_pipeline/dailyhot_client.py tests/core_pipeline/test_dailyhot_client.py
git commit -m "feat: collect dailyhot records by route"
```

Expected: commit succeeds.

## 4. Task 3: Topic Detail Collection

**Files:**

- Create: `src/core_pipeline/detail_collector.py`
- Create: `tests/core_pipeline/test_detail_collector.py`
- Modify: `src/core_pipeline/providers/baidu.py`

- [ ] **Step 1: Write failing detail collector tests**

Create `tests/core_pipeline/test_detail_collector.py`:

```python
import unittest

from src.core_pipeline.detail_collector import collect_topic_details
from src.core_pipeline.types import HotRecord


def hot_record(record_id: str, platform: str, title: str) -> HotRecord:
    return HotRecord(
        id=record_id,
        source="dailyhotapi",
        platform=platform,
        route=platform,
        category="core_discovery",
        title=title,
        rank=1,
        hot_value="100",
        url="https://example.com/hot",
        mobile_url="",
        desc="热榜摘要不能替代详情",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-22T20:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )


class DetailCollectorTests(unittest.TestCase):
    def test_collect_topic_details_writes_non_empty_baidu_detail_from_search_results(self):
        topic = {
            "topic_key": "某事件",
            "canonical_title": "某事件",
            "hot_record_ids": ["hot_weibo_001"],
            "records": [hot_record("hot_weibo_001", "weibo", "某事件")],
        }

        def search_provider(query: str):
            if "怎么回事" in query:
                return [{"title": "某事件详情", "snippet": "这里是事件的详细经过", "url": "https://news.example.com/a"}]
            return []

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=search_provider,
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        )

        baidu_rows = [row for row in evidence if row.platform == "baidu"]
        self.assertEqual(baidu_rows[0].fetch_status, "ok")
        self.assertIn("这里是事件的详细经过", baidu_rows[0].content)

    def test_collect_topic_details_records_empty_content_when_search_has_no_detail(self):
        topic = {
            "topic_key": "某事件",
            "canonical_title": "某事件",
            "hot_record_ids": ["hot_weibo_001"],
            "records": [hot_record("hot_weibo_001", "weibo", "某事件")],
        }

        evidence = collect_topic_details(
            topics=[topic],
            fetched_at="2026-06-22T20:10:00+08:00",
            search_provider=lambda query: [],
            session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        )

        self.assertTrue(any(row.fetch_status == "empty_content" for row in evidence if row.platform == "baidu"))
        self.assertTrue(any(row.fetch_status == "login_required" for row in evidence if row.platform == "weibo"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_detail_collector -v
```

Expected: FAIL because `src.core_pipeline.detail_collector` does not exist.

- [ ] **Step 3: Add Baidu query helper**

Append to `src/core_pipeline/providers/baidu.py`:

```python
def detail_queries_for_title(title: str) -> list[str]:
    clean_title = str(title).strip()
    return [
        clean_title,
        f"{clean_title} 怎么回事",
        f"{clean_title} 最新进展",
    ]
```

- [ ] **Step 4: Implement detail collector**

Create `src/core_pipeline/detail_collector.py`:

```python
from collections.abc import Callable
from typing import Any

from src.core_pipeline.providers.baidu import collect_baidu_detail, detail_queries_for_title
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.types import DetailEvidence, HotRecord


SearchProvider = Callable[[str], list[dict[str, str]]]


def collect_topic_details(
    topics: list[dict[str, Any]],
    fetched_at: str,
    search_provider: SearchProvider,
    session_status: dict[str, str],
) -> list[DetailEvidence]:
    evidence_rows: list[DetailEvidence] = []
    for topic in topics:
        records = [record for record in topic.get("records", []) if isinstance(record, HotRecord)]
        if not records:
            continue
        representative = records[0]
        query_results: list[dict[str, str]] = []
        used_query = representative.title
        for query in detail_queries_for_title(representative.title):
            results = search_provider(query)
            if results:
                query_results = results
                used_query = query
                break
        baidu_evidence = collect_baidu_detail(representative, fetched_at, query_results)
        baidu_evidence = DetailEvidence(
            evidence_id=baidu_evidence.evidence_id,
            topic_key=baidu_evidence.topic_key,
            related_hot_record_ids=list(topic.get("hot_record_ids", representative.id and [representative.id])),
            platform=baidu_evidence.platform,
            source_role=baidu_evidence.source_role,
            source_method=baidu_evidence.source_method,
            query=used_query,
            url=baidu_evidence.url,
            title=baidu_evidence.title,
            content=baidu_evidence.content,
            author=baidu_evidence.author,
            published_at=baidu_evidence.published_at,
            metrics=baidu_evidence.metrics,
            comments_preview=baidu_evidence.comments_preview,
            result_urls=baidu_evidence.result_urls,
            raw_snapshot_path=baidu_evidence.raw_snapshot_path,
            screenshot_path=baidu_evidence.screenshot_path,
            fetched_at=baidu_evidence.fetched_at,
            fetch_status=baidu_evidence.fetch_status,
            error_type=baidu_evidence.error_type,
            confidence=baidu_evidence.confidence,
            raw_payload=baidu_evidence.raw_payload,
        )
        evidence_rows.append(baidu_evidence)
        evidence_rows.append(
            collect_weibo_detail(
                representative,
                fetched_at,
                session_status.get("weibo", "login_required"),
                [],
            )
        )
        evidence_rows.append(
            collect_xiaohongshu_detail(
                representative,
                fetched_at,
                session_status.get("xiaohongshu", "login_required"),
                [],
            )
        )
    return evidence_rows
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_detail_collector tests.core_pipeline.test_required_providers -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/core_pipeline/detail_collector.py src/core_pipeline/providers/baidu.py tests/core_pipeline/test_detail_collector.py
git commit -m "feat: collect topic detail evidence"
```

Expected: commit succeeds.

## 5. Task 4: Recent Details CLI And Report Output

**Files:**

- Modify: `src/core_pipeline/run.py`
- Modify: `src/core_pipeline/report_renderer.py`
- Modify: `tests/core_pipeline/test_run.py`
- Modify: `tests/core_pipeline/test_report_renderer.py`
- Modify: `Makefile`

- [ ] **Step 1: Add failing run tests**

Append to `tests/core_pipeline/test_run.py`:

```python
from pathlib import Path
import tempfile

from src.core_pipeline.run import run_recent_detail_collection


class RecentDetailRunTests(unittest.TestCase):
    def test_run_recent_detail_collection_writes_hot_records_evidence_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def route_fetcher(route: str):
                return {"data": [{"title": "某事件", "hot": "100", "url": "https://example.com/hot"}]}

            def search_provider(query: str):
                return [{"title": "某事件详情", "snippet": "详细内容", "url": "https://example.com/detail"}]

            result = run_recent_detail_collection(
                window="today",
                root=root,
                routes=("weibo",),
                route_fetcher=route_fetcher,
                search_provider=search_provider,
                session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
                now=lambda: "2026-06-22T20:00:00+08:00",
            )

            self.assertEqual(result["topics_count"], 1)
            self.assertTrue((root / "data/raw/dailyhot_records.json").exists())
            self.assertTrue((root / "data/evidence/detail_evidence.json").exists())
            self.assertTrue((root / "reports/recent_hot_topics_digest.md").exists())
```

- [ ] **Step 2: Add failing report renderer test**

Append to `tests/core_pipeline/test_report_renderer.py`:

```python
from src.core_pipeline.report_renderer import render_recent_hot_topics_report
from src.core_pipeline.types import DetailEvidence, HotRecord


class RecentHotTopicsReportTests(unittest.TestCase):
    def test_recent_report_shows_detail_status_and_snippet(self):
        record = HotRecord(
            id="hot_weibo_001",
            source="dailyhotapi",
            platform="weibo",
            route="weibo",
            category="core_discovery",
            title="某事件",
            rank=1,
            hot_value="100",
            url="https://example.com/hot",
            mobile_url="",
            desc="",
            author="",
            cover="",
            timestamp="",
            captured_at="2026-06-22T20:00:00+08:00",
            raw_payload={},
            fetch_status="ok",
            error_type=None,
        )
        evidence = DetailEvidence(
            evidence_id="evidence_baidu_hot_weibo_001",
            topic_key="某事件",
            related_hot_record_ids=["hot_weibo_001"],
            platform="baidu",
            source_role="required",
            source_method="search_results",
            query="某事件 怎么回事",
            url="https://example.com/detail",
            title="某事件详情",
            content="这里是详细内容",
            author="",
            published_at="",
            metrics={},
            comments_preview=[],
            result_urls=["https://example.com/detail"],
            raw_snapshot_path="",
            screenshot_path="",
            fetched_at="2026-06-22T20:10:00+08:00",
            fetch_status="ok",
            error_type=None,
            confidence="medium",
            raw_payload={},
        )

        markdown = render_recent_hot_topics_report(
            topics=[{"topic_key": "某事件", "canonical_title": "某事件", "hot_record_ids": ["hot_weibo_001"], "records": [record]}],
            evidence_rows=[evidence],
            generated_at="2026-06-22T20:20:00+08:00",
            window="today",
        )

        self.assertIn("# 近期热点详情汇总", markdown)
        self.assertIn("采集窗口：`today`", markdown)
        self.assertIn("这里是详细内容", markdown)
        self.assertIn("baidu：`ok`", markdown)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_run tests.core_pipeline.test_report_renderer -v
```

Expected: FAIL because `run_recent_detail_collection` and `render_recent_hot_topics_report` are not defined.

- [ ] **Step 4: Implement recent report renderer**

Append to `src/core_pipeline/report_renderer.py`:

```python
from src.core_pipeline.types import DetailEvidence, HotRecord


def render_recent_hot_topics_report(
    topics: list[dict[str, object]],
    evidence_rows: list[DetailEvidence],
    generated_at: str,
    window: str,
) -> str:
    evidence_by_topic: dict[str, list[DetailEvidence]] = {}
    for evidence in evidence_rows:
        evidence_by_topic.setdefault(evidence.topic_key, []).append(evidence)
    topics_with_detail = sum(
        1
        for topic in topics
        if any(
            row.fetch_status == "ok" and row.content.strip()
            for row in evidence_by_topic.get(str(topic.get("canonical_title", "")), [])
        )
    )
    lines = [
        "# 近期热点详情汇总",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 采集窗口：`{window}`",
        f"- 去重后话题数量：`{len(topics)}`",
        f"- 有详情话题数量：`{topics_with_detail}`",
        f"- 缺失详情话题数量：`{len(topics) - topics_with_detail}`",
        "",
    ]
    for index, topic in enumerate(topics, start=1):
        title = str(topic.get("canonical_title", "未命名话题"))
        topic_key = str(topic.get("topic_key", title))
        records = [record for record in topic.get("records", []) if isinstance(record, HotRecord)]
        evidence_for_topic = evidence_by_topic.get(topic_key, [])
        lines.extend([f"## {index}. {title}", "", "### 热榜来源", ""])
        if records:
            for record in records:
                lines.append(f"- `{record.platform}`：排名 `{record.rank}`，热度 `{record.hot_value}`")
        else:
            lines.append("- 未记录热榜来源。")
        lines.extend(["", "### 详细信息", ""])
        ok_rows = [row for row in evidence_for_topic if row.fetch_status == "ok" and row.content.strip()]
        if ok_rows:
            for row in ok_rows:
                snippet = row.content.strip().replace("\n", " ")[:240]
                url = row.result_urls[0] if row.result_urls else row.url
                lines.append(f"- `{row.platform}` / `{row.query}` / {url}")
                lines.append(f"  {snippet}")
        else:
            lines.append("- 未采集到非空详情。")
        lines.extend(["", "### 平台详情状态", ""])
        if evidence_for_topic:
            for row in evidence_for_topic:
                lines.append(f"- {row.platform}：`{row.fetch_status}`")
        else:
            lines.append("- 未生成详情证据。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 5: Implement recent detail CLI orchestration**

Modify `src/core_pipeline/run.py` so it contains these imports and functions in addition to existing code:

```python
from src.core_pipeline.dailyhot_client import collect_dailyhot_records, fetch_dailyhot_route
from src.core_pipeline.detail_collector import collect_topic_details
from src.core_pipeline.recent_topics import collection_window_days, deduplicate_hot_records
from src.core_pipeline.report_renderer import render_recent_hot_topics_report
from src.core_pipeline.source_registry import ALL_DAILYHOT_ROUTES
```

Add these functions:

```python
def default_search_provider(query: str) -> list[dict[str, str]]:
    return []


def rooted_output_paths(root: Path) -> dict[str, Path]:
    return {key: root / value for key, value in output_paths().items()} | {
        "recent_markdown_report": root / "reports/recent_hot_topics_digest.md"
    }


def run_recent_detail_collection(
    window: str,
    root: Path = Path("."),
    routes: tuple[str, ...] = ALL_DAILYHOT_ROUTES,
    route_fetcher=None,
    search_provider=default_search_provider,
    session_status: dict[str, str] | None = None,
    now=now_shanghai_iso,
) -> dict[str, int]:
    collection_window_days(window)
    captured_at = now()
    if route_fetcher is None:
        route_fetcher = lambda route: fetch_dailyhot_route("https://dailyhotapi.now.sh", route)
    records = collect_dailyhot_records(routes=routes, captured_at=captured_at, fetcher=route_fetcher)
    topics = deduplicate_hot_records([record for record in records if record.fetch_status == "ok"])
    status = session_status if session_status is not None else check_required_sessions()
    evidence_rows = collect_topic_details(
        topics=topics,
        fetched_at=captured_at,
        search_provider=search_provider,
        session_status=status,
    )
    paths = rooted_output_paths(root)
    write_json_list(paths["hot_records"], [record.to_dict() for record in records])
    serializable_topics = [
        {
            "topic_key": topic["topic_key"],
            "canonical_title": topic["canonical_title"],
            "hot_record_ids": topic["hot_record_ids"],
            "platforms": topic["platforms"],
            "best_rank": topic["best_rank"],
        }
        for topic in topics
    ]
    write_json_list(paths["topic_clusters"], serializable_topics)
    write_json_list(paths["detail_evidence"], [row.to_dict() for row in evidence_rows])
    report = render_recent_hot_topics_report(
        topics=topics,
        evidence_rows=evidence_rows,
        generated_at=captured_at,
        window=window,
    )
    paths["recent_markdown_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["recent_markdown_report"].write_text(report, encoding="utf-8")
    return {
        "hot_records_count": len(records),
        "topics_count": len(topics),
        "detail_evidence_count": len(evidence_rows),
    }
```

Update `main()` command choices and branch:

```python
parser.add_argument("command", choices=("paths", "render-report", "collect-core-details", "collect-recent-details"))
parser.add_argument("--window", choices=("today", "last_7_days"), default="today")
...
if args.command == "collect-recent-details":
    run_recent_detail_collection(window=args.window)
```

- [ ] **Step 6: Add Makefile target**

Modify `Makefile`:

```makefile
.PHONY: collect-recent-hot-details

collect-recent-hot-details:
	$(PYTHON) -m src.core_pipeline.run collect-recent-details --window today
```

- [ ] **Step 7: Run tests to verify pass**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_run tests.core_pipeline.test_report_renderer -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/core_pipeline/run.py src/core_pipeline/report_renderer.py tests/core_pipeline/test_run.py tests/core_pipeline/test_report_renderer.py Makefile
git commit -m "feat: add recent hot detail collection command"
```

Expected: commit succeeds.

## 6. Task 5: End-To-End Verification

**Files:**

- Modify only files from previous tasks if verification reveals defects.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_recent_topics tests.core_pipeline.test_dailyhot_client tests.core_pipeline.test_detail_collector tests.core_pipeline.test_run tests.core_pipeline.test_report_renderer -v
```

Expected: all tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run fixture-backed smoke test**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from src.core_pipeline.run import run_recent_detail_collection

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    result = run_recent_detail_collection(
        window="today",
        root=root,
        routes=("weibo", "baidu"),
        route_fetcher=lambda route: {"data": [{"title": "测试热点", "hot": "100", "url": "https://example.com/hot"}]},
        search_provider=lambda query: [{"title": "测试热点详情", "snippet": "这是可用的详细信息", "url": "https://example.com/detail"}],
        session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        now=lambda: "2026-06-22T20:00:00+08:00",
    )
    print(result)
    print((root / "reports/recent_hot_topics_digest.md").read_text(encoding="utf-8")[:300])
PY
```

Expected output contains:

```text
'topics_count': 1
这是可用的详细信息
```

- [ ] **Step 4: Verify report distinguishes missing details**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from src.core_pipeline.run import run_recent_detail_collection

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    run_recent_detail_collection(
        window="today",
        root=root,
        routes=("weibo",),
        route_fetcher=lambda route: {"data": [{"title": "无详情热点", "hot": "100"}]},
        search_provider=lambda query: [],
        session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        now=lambda: "2026-06-22T20:00:00+08:00",
    )
    report = (root / "reports/recent_hot_topics_digest.md").read_text(encoding="utf-8")
    print(report)
PY
```

Expected output contains:

```text
未采集到非空详情
baidu：`empty_content`
```

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intended runtime files or pre-existing unrelated changes remain. Do not revert unrelated user changes.

- [ ] **Step 6: Commit verification fixes if needed**

Run only after making verification fixes:

```bash
git add src/core_pipeline tests/core_pipeline Makefile
git commit -m "fix: stabilize recent hot detail collection"
```

Expected: commit succeeds when fixes exist. Skip if no fixes were needed.

## 7. Execution Notes For Subagents

- Each task should be handled by a fresh implementer subagent.
- The controller should provide the exact task text to the subagent; do not ask the subagent to read the whole plan.
- After each task, run a spec-compliance review subagent, then a code-quality review subagent.
- Do not start the next task until both reviews pass.
- Keep commits task-scoped.
- Do not revert pre-existing uncommitted files in `data/`, `reports/`, `src/demo_collect_hot_topics.py`, `src/enrich_sources.py`, `src/generate_reports.py`, or `tools/run-demo.sh`; they were already dirty before this plan.

## 8. Self-Review

Spec coverage:

- `today` and `last_7_days` are covered by Task 1 and Task 4 CLI arguments.
- Hot topic collection is covered by Task 2 and Task 4.
- Basic deduplication is covered by Task 1.
- Detail collection with non-empty `content` is covered by Task 3.
- Explicit detail failure status is covered by Task 3 and Task 4 report tests.
- JSON outputs are covered by Task 4.
- Markdown output is covered by Task 4.
- End-to-end smoke verification is covered by Task 5.

Placeholder scan:

- The plan avoids placeholder markers and unnamed validation.
- Future work such as trust scoring and analysis is intentionally excluded.

Type consistency:

- The plan reuses existing `HotRecord` and `DetailEvidence`.
- `deduplicate_hot_records()` returns dictionaries because the first version needs runtime record objects for report rendering; Task 4 writes a serializable projection to `topic_clusters.json`.
- `collect_topic_details()` accepts injectable search and session providers so tests do not require network or browser state.
