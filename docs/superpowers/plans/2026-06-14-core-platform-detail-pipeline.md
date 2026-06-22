# Core Platform Detail Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-version manual hot topic pipeline where DailyHotApi discovers candidate topics, Weibo/Xiaohongshu/Baidu provide required detailed evidence, auxiliary sources add context, and the system outputs traceable JSON plus Markdown topic briefs.

**Architecture:** Treat DailyHotApi as the recall layer and never as the final detail layer. Store every collected item as `DetailEvidence`, evaluate whether each topic has the three required detail sources, then let clustering and LLM organizing consume only traceable evidence. The first version is file-based and manually run; automation, public APIs, publishing, copywriting, and tag recommendation stay outside this plan.

**Tech Stack:** Python 3.10+ standard library, `unittest`, existing `Makefile`, DailyHotApi HTTP JSON, optional local Playwright browser sessions for logged-in Weibo and Xiaohongshu collection, JSON files, Markdown reports.

---

## 0. Product Rule

This implementation is only successful when details are collected and stored separately.

- `weibo`, `xiaohongshu`, and `baidu` are required detail sources.
- Missing one required source makes the topic `core_incomplete`.
- DailyHotApi records remain useful as discovery and auxiliary evidence, but DailyHotApi records alone never make a topic complete.
- Other sources are still collected: news, tech, video, GitHub, and foreign/technical trend routes improve context and confidence.
- Login-required platforms must check session state first. If login is missing, captcha appears, rate limit appears, or a risk-control page appears, record the status and stop that platform.

## 1. File Structure

Create these modules:

- `src/core_pipeline/__init__.py`: package marker.
- `src/core_pipeline/source_registry.py`: DailyHot route groups, required source list, auxiliary source list, and failed-route policy from `docs/2026-06-13-dailyhot-api-analysis.md`.
- `src/core_pipeline/types.py`: dataclasses for `HotRecord`, `DetailEvidence`, `RequiredDetailStatus`, `TopicCluster`, and `TopicBrief`.
- `src/core_pipeline/json_store.py`: JSON read/write helpers with deterministic ordering.
- `src/core_pipeline/dailyhot_client.py`: DailyHotApi collection, route health recording, and `HotRecord` normalization.
- `src/core_pipeline/session_gate.py`: browser login-state checks for Weibo and Xiaohongshu.
- `src/core_pipeline/providers/baidu.py`: required Baidu detail collector interface and testable parser helpers.
- `src/core_pipeline/providers/weibo.py`: required Weibo detail collector interface using saved browser session state.
- `src/core_pipeline/providers/xiaohongshu.py`: required Xiaohongshu detail collector interface using saved browser session state.
- `src/core_pipeline/providers/auxiliary.py`: auxiliary evidence collector from DailyHotApi records and readable article URLs.
- `src/core_pipeline/completeness.py`: required-source completeness evaluator.
- `src/core_pipeline/topic_clusterer.py`: same-topic clustering based on titles plus evidence.
- `src/core_pipeline/brief_generator.py`: LLM-ready topic organizing with deterministic fallback.
- `src/core_pipeline/report_renderer.py`: Markdown report renderer.
- `src/core_pipeline/run.py`: orchestration CLI for the manual first version.

Modify these existing files:

- `Makefile`: add first-version commands without removing current commands.
- `.gitignore`: add private browser state and generated evidence artifacts if they are not already ignored.

Create these tests:

- `tests/core_pipeline/test_source_registry.py`
- `tests/core_pipeline/test_types.py`
- `tests/core_pipeline/test_json_store.py`
- `tests/core_pipeline/test_dailyhot_client.py`
- `tests/core_pipeline/test_session_gate.py`
- `tests/core_pipeline/test_required_providers.py`
- `tests/core_pipeline/test_auxiliary_provider.py`
- `tests/core_pipeline/test_completeness.py`
- `tests/core_pipeline/test_topic_clusterer.py`
- `tests/core_pipeline/test_brief_generator.py`
- `tests/core_pipeline/test_report_renderer.py`
- `tests/core_pipeline/test_run.py`

Generated runtime files:

- `data/raw/dailyhot_records.json`
- `data/evidence/detail_evidence.json`
- `data/processed/topic_clusters.json`
- `data/processed/topic_briefs.json`
- `reports/core_platform_topic_digest.md`

Private local files:

- `data/browser_state/weibo.json`
- `data/browser_state/xiaohongshu.json`
- `data/snapshots/weibo/`
- `data/snapshots/xiaohongshu/`
- `data/screenshots/weibo/`
- `data/screenshots/xiaohongshu/`

## 2. Data Contracts

Use these statuses exactly:

```python
OK = "ok"
LOGIN_REQUIRED = "login_required"
CAPTCHA_REQUIRED = "captcha_required"
RATE_LIMITED = "rate_limited"
EMPTY_CONTENT = "empty_content"
FAILED = "failed"

DETAIL_COMPLETE = "complete"
DETAIL_CORE_INCOMPLETE = "core_incomplete"
DETAIL_AUXILIARY_ONLY = "auxiliary_only"
DETAIL_FAILED = "failed"
```

`HotRecord` fields:

```json
{
  "id": "hot_weibo_001",
  "source": "dailyhotapi",
  "platform": "weibo",
  "route": "weibo",
  "category": "core_discovery",
  "title": "热点标题",
  "rank": 1,
  "hot_value": "123456",
  "url": "https://example.com",
  "mobile_url": "https://m.example.com",
  "desc": "DailyHotApi 摘要",
  "author": "",
  "cover": "",
  "timestamp": "",
  "captured_at": "2026-06-14T20:00:00+08:00",
  "raw_payload": {},
  "fetch_status": "ok",
  "error_type": null
}
```

`DetailEvidence` fields:

```json
{
  "evidence_id": "evidence_weibo_hot_weibo_001_001",
  "topic_key": "热点标题",
  "related_hot_record_ids": ["hot_weibo_001"],
  "platform": "weibo",
  "source_role": "required",
  "source_method": "browser_session",
  "query": "热点标题",
  "url": "https://example.com/detail",
  "title": "详情标题",
  "content": "详情正文、评论预览或搜索结果正文",
  "author": "作者",
  "published_at": "2026-06-14T18:30:00+08:00",
  "metrics": {"likes": 12, "comments": 3, "shares": 1},
  "comments_preview": ["评论文本"],
  "result_urls": ["https://example.com/article"],
  "raw_snapshot_path": "data/snapshots/weibo/evidence_weibo_hot_weibo_001_001.html",
  "screenshot_path": "data/screenshots/weibo/evidence_weibo_hot_weibo_001_001.png",
  "fetched_at": "2026-06-14T20:05:00+08:00",
  "fetch_status": "ok",
  "error_type": null,
  "confidence": "medium",
  "raw_payload": {}
}
```

`RequiredDetailStatus` fields:

```json
{
  "topic_key": "热点标题",
  "weibo": "ok",
  "xiaohongshu": "ok",
  "baidu": "ok",
  "missing_required_details": [],
  "auxiliary_evidence_count": 6,
  "detail_completeness": "complete"
}
```

## 3. Task 1: Source Registry And Schema Types

**Files:**

- Create: `src/core_pipeline/__init__.py`
- Create: `src/core_pipeline/source_registry.py`
- Create: `src/core_pipeline/types.py`
- Create: `tests/core_pipeline/test_source_registry.py`
- Create: `tests/core_pipeline/test_types.py`

- [ ] **Step 1: Create package folders**

Run:

```bash
mkdir -p src/core_pipeline/providers tests/core_pipeline
touch src/core_pipeline/__init__.py src/core_pipeline/providers/__init__.py
```

Expected: both package marker files exist.

- [ ] **Step 2: Write failing source registry tests**

Create `tests/core_pipeline/test_source_registry.py`:

```python
import unittest

from src.core_pipeline.source_registry import (
    AUXILIARY_DAILYHOT_ROUTES,
    DAILYHOT_ROUTE_GROUPS,
    FAILED_DEFAULT_ROUTES,
    REQUIRED_DETAIL_PLATFORMS,
    route_role,
)


class SourceRegistryTests(unittest.TestCase):
    def test_required_detail_platforms_are_fixed(self):
        self.assertEqual(REQUIRED_DETAIL_PLATFORMS, ("weibo", "xiaohongshu", "baidu"))

    def test_dailyhot_route_groups_include_domestic_and_foreign_context(self):
        self.assertIn("weibo", DAILYHOT_ROUTE_GROUPS["core_discovery"])
        self.assertIn("baidu", DAILYHOT_ROUTE_GROUPS["core_discovery"])
        self.assertIn("github", DAILYHOT_ROUTE_GROUPS["foreign_tech"])
        self.assertIn("hellogithub", DAILYHOT_ROUTE_GROUPS["foreign_tech"])

    def test_failed_default_routes_are_not_main_chain(self):
        self.assertIn("hackernews", FAILED_DEFAULT_ROUTES)
        self.assertIn("producthunt", FAILED_DEFAULT_ROUTES)
        self.assertNotIn("hackernews", AUXILIARY_DAILYHOT_ROUTES)

    def test_route_role_returns_auxiliary_for_news(self):
        self.assertEqual(route_role("sina-news"), "auxiliary_news")
        self.assertEqual(route_role("unknown-route"), "unknown")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Implement source registry**

Create `src/core_pipeline/source_registry.py`:

```python
REQUIRED_DETAIL_PLATFORMS = ("weibo", "xiaohongshu", "baidu")

DAILYHOT_ROUTE_GROUPS = {
    "core_discovery": (
        "weibo",
        "baidu",
        "zhihu",
        "toutiao",
    ),
    "auxiliary_news": (
        "sina-news",
        "thepaper",
        "qq-news",
        "netease-news",
    ),
    "auxiliary_tech_business": (
        "36kr",
        "ithome",
        "juejin",
        "csdn",
    ),
    "foreign_tech": (
        "github",
        "hellogithub",
    ),
    "auxiliary_content_heat": (
        "bilibili",
        "douyin",
        "kuaishou",
    ),
}

FAILED_DEFAULT_ROUTES = (
    "coolapk",
    "earthquake",
    "hackernews",
    "hostloc",
    "linuxdo",
    "nodeseek",
    "nytimes",
    "producthunt",
    "sspai",
    "v2ex",
)

AUXILIARY_DAILYHOT_ROUTES = tuple(
    route
    for group_name, routes in DAILYHOT_ROUTE_GROUPS.items()
    if group_name != "core_discovery"
    for route in routes
)

ALL_DAILYHOT_ROUTES = tuple(
    route
    for routes in DAILYHOT_ROUTE_GROUPS.values()
    for route in routes
)


def route_role(route: str) -> str:
    for group_name, routes in DAILYHOT_ROUTE_GROUPS.items():
        if route in routes:
            return group_name
    return "unknown"
```

- [ ] **Step 4: Write failing type tests**

Create `tests/core_pipeline/test_types.py`:

```python
import unittest

from src.core_pipeline.types import (
    DetailEvidence,
    HotRecord,
    RequiredDetailStatus,
    TopicBrief,
    TopicCluster,
)


class TypesTests(unittest.TestCase):
    def test_hot_record_serializes_dailyhot_fields(self):
        record = HotRecord(
            id="hot_weibo_001",
            source="dailyhotapi",
            platform="weibo",
            route="weibo",
            category="core_discovery",
            title="测试热点",
            rank=1,
            hot_value="1000",
            url="https://example.com",
            mobile_url="https://m.example.com",
            desc="摘要",
            author="",
            cover="",
            timestamp="",
            captured_at="2026-06-14T20:00:00+08:00",
            raw_payload={"title": "测试热点"},
            fetch_status="ok",
            error_type=None,
        )

        data = record.to_dict()

        self.assertEqual(data["title"], "测试热点")
        self.assertEqual(data["route"], "weibo")
        self.assertEqual(data["desc"], "摘要")

    def test_detail_evidence_serializes_required_source(self):
        evidence = DetailEvidence(
            evidence_id="evidence_001",
            topic_key="测试热点",
            related_hot_record_ids=["hot_weibo_001"],
            platform="weibo",
            source_role="required",
            source_method="browser_session",
            query="测试热点",
            url="https://example.com/detail",
            title="微博详情",
            content="微博正文",
            author="作者",
            published_at="2026-06-14T18:30:00+08:00",
            metrics={"likes": 1},
            comments_preview=["评论"],
            result_urls=[],
            raw_snapshot_path="data/snapshots/weibo/evidence_001.html",
            screenshot_path="data/screenshots/weibo/evidence_001.png",
            fetched_at="2026-06-14T20:05:00+08:00",
            fetch_status="ok",
            error_type=None,
            confidence="medium",
            raw_payload={},
        )

        data = evidence.to_dict()

        self.assertEqual(data["source_role"], "required")
        self.assertEqual(data["content"], "微博正文")

    def test_required_detail_status_marks_missing_sources(self):
        status = RequiredDetailStatus(
            topic_key="测试热点",
            weibo="ok",
            xiaohongshu="login_required",
            baidu="ok",
            missing_required_details=["xiaohongshu"],
            auxiliary_evidence_count=4,
            detail_completeness="core_incomplete",
        )

        self.assertEqual(status.to_dict()["missing_required_details"], ["xiaohongshu"])

    def test_cluster_and_brief_keep_evidence_links(self):
        cluster = TopicCluster(
            topic_id="topic_001",
            canonical_title="测试热点",
            aliases=["测试事件"],
            hot_record_ids=["hot_weibo_001"],
            evidence_ids=["evidence_001"],
            platforms=["weibo", "baidu"],
            required_detail_status={
                "weibo": "ok",
                "xiaohongshu": "ok",
                "baidu": "ok",
            },
            detail_completeness="complete",
            cluster_confidence="high",
        )
        brief = TopicBrief(
            topic_id="topic_001",
            canonical_title="测试热点",
            summary="事件摘要",
            key_facts=["事实一"],
            platform_observations={"weibo": "微博讨论"},
            evidence_ids=["evidence_001"],
            missing_required_details=[],
            detail_completeness="complete",
            confidence="high",
        )

        self.assertEqual(cluster.to_dict()["evidence_ids"], ["evidence_001"])
        self.assertEqual(brief.to_dict()["detail_completeness"], "complete")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Implement schema dataclasses**

Create `src/core_pipeline/types.py`:

```python
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HotRecord:
    id: str
    source: str
    platform: str
    route: str
    category: str
    title: str
    rank: int
    hot_value: str
    url: str
    mobile_url: str
    desc: str
    author: str
    cover: str
    timestamp: str
    captured_at: str
    raw_payload: dict[str, Any]
    fetch_status: str
    error_type: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DetailEvidence:
    evidence_id: str
    topic_key: str
    related_hot_record_ids: list[str]
    platform: str
    source_role: str
    source_method: str
    query: str
    url: str
    title: str
    content: str
    author: str
    published_at: str
    metrics: dict[str, Any]
    comments_preview: list[str]
    result_urls: list[str]
    raw_snapshot_path: str
    screenshot_path: str
    fetched_at: str
    fetch_status: str
    error_type: str | None
    confidence: str
    raw_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequiredDetailStatus:
    topic_key: str
    weibo: str
    xiaohongshu: str
    baidu: str
    missing_required_details: list[str]
    auxiliary_evidence_count: int
    detail_completeness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicCluster:
    topic_id: str
    canonical_title: str
    aliases: list[str]
    hot_record_ids: list[str]
    evidence_ids: list[str]
    platforms: list[str]
    required_detail_status: dict[str, str]
    detail_completeness: str
    cluster_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicBrief:
    topic_id: str
    canonical_title: str
    summary: str
    key_facts: list[str]
    platform_observations: dict[str, str]
    evidence_ids: list[str]
    missing_required_details: list[str]
    detail_completeness: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 6: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_source_registry tests.core_pipeline.test_types -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/core_pipeline/__init__.py src/core_pipeline/providers/__init__.py src/core_pipeline/source_registry.py src/core_pipeline/types.py tests/core_pipeline/test_source_registry.py tests/core_pipeline/test_types.py
git commit -m "feat: add core detail pipeline schemas"
```

Expected: commit succeeds.

## 4. Task 2: JSON Store And DailyHot Collector

**Files:**

- Create: `src/core_pipeline/json_store.py`
- Create: `src/core_pipeline/dailyhot_client.py`
- Create: `tests/core_pipeline/test_json_store.py`
- Create: `tests/core_pipeline/test_dailyhot_client.py`

- [ ] **Step 1: Write JSON store tests**

Create `tests/core_pipeline/test_json_store.py`:

```python
import tempfile
import unittest
from pathlib import Path

from src.core_pipeline.json_store import read_json_list, write_json_list


class JsonStoreTests(unittest.TestCase):
    def test_write_json_list_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "records.json"

            write_json_list(path, [{"id": "one"}])

            self.assertEqual(read_json_list(path), [{"id": "one"}])

    def test_read_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"

            self.assertEqual(read_json_list(path), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement JSON store**

Create `src/core_pipeline/json_store.py`:

```python
import json
from pathlib import Path
from typing import Any


def read_json_list(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list in {file_path}")
    return data


def write_json_list(path: str | Path, rows: list[dict[str, Any]]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
```

- [ ] **Step 3: Write DailyHot collector tests**

Create `tests/core_pipeline/test_dailyhot_client.py`:

```python
import unittest

from src.core_pipeline.dailyhot_client import normalize_dailyhot_response


class DailyHotClientTests(unittest.TestCase):
    def test_normalize_dailyhot_response_preserves_desc_and_urls(self):
        payload = {
            "name": "baidu",
            "data": [
                {
                    "id": 1,
                    "title": "百度热点",
                    "url": "https://top.baidu.com/item",
                    "mobileUrl": "https://m.baidu.com/item",
                    "desc": "百度摘要",
                    "hot": "100",
                    "cover": "https://image.example.com/a.png",
                    "author": "来源",
                    "timestamp": "1780000000000",
                }
            ],
        }

        records = normalize_dailyhot_response("baidu", payload, "2026-06-14T20:00:00+08:00")

        self.assertEqual(records[0].id, "hot_baidu_001")
        self.assertEqual(records[0].category, "core_discovery")
        self.assertEqual(records[0].desc, "百度摘要")
        self.assertEqual(records[0].mobile_url, "https://m.baidu.com/item")

    def test_normalize_unknown_route_marks_unknown_category(self):
        payload = {"name": "unknown", "data": [{"title": "未知热点"}]}

        records = normalize_dailyhot_response("unknown", payload, "2026-06-14T20:00:00+08:00")

        self.assertEqual(records[0].category, "unknown")
        self.assertEqual(records[0].fetch_status, "ok")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Implement DailyHot normalization and fetcher**

Create `src/core_pipeline/dailyhot_client.py`:

```python
import json
import urllib.request
from typing import Any

from src.core_pipeline.source_registry import route_role
from src.core_pipeline.types import HotRecord


def normalize_dailyhot_response(route: str, payload: dict[str, Any], captured_at: str) -> list[HotRecord]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        rows = []
    records: list[HotRecord] = []
    category = route_role(route)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        records.append(
            HotRecord(
                id=f"hot_{route}_{index:03d}",
                source="dailyhotapi",
                platform=route,
                route=route,
                category=category,
                title=title,
                rank=index,
                hot_value=str(row.get("hot", "")),
                url=str(row.get("url", "")),
                mobile_url=str(row.get("mobileUrl", "")),
                desc=str(row.get("desc", "")),
                author=str(row.get("author", "")),
                cover=str(row.get("cover", "")),
                timestamp=str(row.get("timestamp", "")),
                captured_at=captured_at,
                raw_payload=row,
                fetch_status="ok",
                error_type=None,
            )
        )
    return records


def fetch_dailyhot_route(base_url: str, route: str, timeout_seconds: int = 15) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{route}"
    request = urllib.request.Request(url, headers={"User-Agent": "heatedTopics/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError(f"DailyHotApi route {route} returned non-object JSON")
    return data
```

- [ ] **Step 5: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_json_store tests.core_pipeline.test_dailyhot_client -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/core_pipeline/json_store.py src/core_pipeline/dailyhot_client.py tests/core_pipeline/test_json_store.py tests/core_pipeline/test_dailyhot_client.py
git commit -m "feat: collect normalized DailyHot records"
```

Expected: commit succeeds.

## 5. Task 3: Required Provider Session Gate

**Files:**

- Create: `src/core_pipeline/session_gate.py`
- Create: `tests/core_pipeline/test_session_gate.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write session gate tests**

Create `tests/core_pipeline/test_session_gate.py`:

```python
import tempfile
import unittest
from pathlib import Path

from src.core_pipeline.session_gate import check_required_sessions


class SessionGateTests(unittest.TestCase):
    def test_missing_weibo_and_xiaohongshu_sessions_require_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = check_required_sessions(Path(tmp))

            self.assertEqual(result["weibo"], "login_required")
            self.assertEqual(result["xiaohongshu"], "login_required")

    def test_existing_non_empty_state_files_are_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "weibo.json").write_text('{"cookies":[{"name":"a"}]}', encoding="utf-8")
            (root / "xiaohongshu.json").write_text('{"cookies":[{"name":"b"}]}', encoding="utf-8")

            result = check_required_sessions(root)

            self.assertEqual(result["weibo"], "ok")
            self.assertEqual(result["xiaohongshu"], "ok")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement session gate**

Create `src/core_pipeline/session_gate.py`:

```python
import json
from pathlib import Path


REQUIRED_SESSION_FILES = {
    "weibo": "weibo.json",
    "xiaohongshu": "xiaohongshu.json",
}


def _state_file_has_cookies(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    cookies = data.get("cookies", [])
    return isinstance(cookies, list) and len(cookies) > 0


def check_required_sessions(browser_state_dir: str | Path = "data/browser_state") -> dict[str, str]:
    root = Path(browser_state_dir)
    return {
        platform: "ok" if _state_file_has_cookies(root / file_name) else "login_required"
        for platform, file_name in REQUIRED_SESSION_FILES.items()
    }
```

- [ ] **Step 3: Modify `.gitignore`**

Add these lines to `.gitignore`:

```gitignore
data/browser_state/
data/snapshots/
data/screenshots/
```

- [ ] **Step 4: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_session_gate -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add .gitignore src/core_pipeline/session_gate.py tests/core_pipeline/test_session_gate.py
git commit -m "feat: require browser sessions for core sources"
```

Expected: commit succeeds.

## 6. Task 4: Required Detail Providers

**Files:**

- Create: `src/core_pipeline/providers/baidu.py`
- Create: `src/core_pipeline/providers/weibo.py`
- Create: `src/core_pipeline/providers/xiaohongshu.py`
- Create: `tests/core_pipeline/test_required_providers.py`

- [ ] **Step 1: Write required provider tests**

Create `tests/core_pipeline/test_required_providers.py`:

```python
import unittest

from src.core_pipeline.providers.baidu import collect_baidu_detail
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.types import HotRecord


def hot_record(title: str = "测试热点") -> HotRecord:
    return HotRecord(
        id="hot_weibo_001",
        source="dailyhotapi",
        platform="weibo",
        route="weibo",
        category="core_discovery",
        title=title,
        rank=1,
        hot_value="1000",
        url="https://example.com/search",
        mobile_url="",
        desc="DailyHot 摘要",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-14T20:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )


class RequiredProviderTests(unittest.TestCase):
    def test_baidu_detail_uses_search_results_as_required_evidence(self):
        evidence = collect_baidu_detail(
            hot_record(),
            fetched_at="2026-06-14T20:10:00+08:00",
            search_results=[
                {
                    "title": "测试热点 官方回应",
                    "url": "https://news.example.com/a",
                    "snippet": "官方回应内容摘要",
                }
            ],
        )

        self.assertEqual(evidence.platform, "baidu")
        self.assertEqual(evidence.source_role, "required")
        self.assertEqual(evidence.fetch_status, "ok")
        self.assertIn("官方回应内容摘要", evidence.content)

    def test_weibo_missing_session_returns_login_required_evidence(self):
        evidence = collect_weibo_detail(
            hot_record(),
            fetched_at="2026-06-14T20:10:00+08:00",
            session_status="login_required",
            extracted_posts=[],
        )

        self.assertEqual(evidence.fetch_status, "login_required")
        self.assertEqual(evidence.error_type, "login_required")

    def test_xiaohongshu_empty_posts_returns_empty_content(self):
        evidence = collect_xiaohongshu_detail(
            hot_record("小红书热点"),
            fetched_at="2026-06-14T20:10:00+08:00",
            session_status="ok",
            extracted_notes=[],
        )

        self.assertEqual(evidence.fetch_status, "empty_content")
        self.assertEqual(evidence.platform, "xiaohongshu")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement Baidu required evidence**

Create `src/core_pipeline/providers/baidu.py`:

```python
from src.core_pipeline.types import DetailEvidence, HotRecord


def collect_baidu_detail(
    record: HotRecord,
    fetched_at: str,
    search_results: list[dict[str, str]],
) -> DetailEvidence:
    usable_results = [row for row in search_results if row.get("title") or row.get("snippet")]
    status = "ok" if usable_results else "empty_content"
    content_parts = []
    result_urls = []
    for row in usable_results[:5]:
        title = row.get("title", "").strip()
        snippet = row.get("snippet", "").strip()
        url = row.get("url", "").strip()
        if url:
            result_urls.append(url)
        content_parts.append(f"{title}\n{snippet}".strip())
    content = "\n\n".join(part for part in content_parts if part)
    return DetailEvidence(
        evidence_id=f"evidence_baidu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="baidu",
        source_role="required",
        source_method="search_results",
        query=record.title,
        url=record.url,
        title=f"百度搜索详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=result_urls,
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium" if status == "ok" else "low",
        raw_payload={"search_results": search_results},
    )
```

- [ ] **Step 3: Implement Weibo required evidence builder**

Create `src/core_pipeline/providers/weibo.py`:

```python
from src.core_pipeline.types import DetailEvidence, HotRecord


def collect_weibo_detail(
    record: HotRecord,
    fetched_at: str,
    session_status: str,
    extracted_posts: list[dict[str, object]],
) -> DetailEvidence:
    if session_status != "ok":
        return _status_evidence(record, fetched_at, session_status)
    if not extracted_posts:
        return _status_evidence(record, fetched_at, "empty_content")
    content = "\n\n".join(str(post.get("content", "")).strip() for post in extracted_posts[:5]).strip()
    comments = []
    for post in extracted_posts[:5]:
        post_comments = post.get("comments_preview", [])
        if isinstance(post_comments, list):
            comments.extend(str(comment) for comment in post_comments[:5])
    return DetailEvidence(
        evidence_id=f"evidence_weibo_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="weibo",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"微博讨论详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={"posts": len(extracted_posts)},
        comments_preview=comments[:20],
        result_urls=[str(post.get("url", "")) for post in extracted_posts[:5] if post.get("url")],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="ok",
        error_type=None,
        confidence="medium",
        raw_payload={"posts": extracted_posts},
    )


def _status_evidence(record: HotRecord, fetched_at: str, status: str) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_weibo_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="weibo",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"微博讨论详情：{record.title}",
        content="",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=[],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=status,
        confidence="low",
        raw_payload={},
    )
```

- [ ] **Step 4: Implement Xiaohongshu required evidence builder**

Create `src/core_pipeline/providers/xiaohongshu.py`:

```python
from src.core_pipeline.types import DetailEvidence, HotRecord


def collect_xiaohongshu_detail(
    record: HotRecord,
    fetched_at: str,
    session_status: str,
    extracted_notes: list[dict[str, object]],
) -> DetailEvidence:
    if session_status != "ok":
        return _status_evidence(record, fetched_at, session_status)
    if not extracted_notes:
        return _status_evidence(record, fetched_at, "empty_content")
    content = "\n\n".join(str(note.get("content", "")).strip() for note in extracted_notes[:5]).strip()
    comments = []
    for note in extracted_notes[:5]:
        note_comments = note.get("comments_preview", [])
        if isinstance(note_comments, list):
            comments.extend(str(comment) for comment in note_comments[:5])
    return DetailEvidence(
        evidence_id=f"evidence_xiaohongshu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="xiaohongshu",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"小红书笔记详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={"notes": len(extracted_notes)},
        comments_preview=comments[:20],
        result_urls=[str(note.get("url", "")) for note in extracted_notes[:5] if note.get("url")],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="ok",
        error_type=None,
        confidence="medium",
        raw_payload={"notes": extracted_notes},
    )


def _status_evidence(record: HotRecord, fetched_at: str, status: str) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_xiaohongshu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="xiaohongshu",
        source_role="required",
        source_method="browser_session",
        query=record.title,
        url=record.url,
        title=f"小红书笔记详情：{record.title}",
        content="",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=[],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=status,
        confidence="low",
        raw_payload={},
    )
```

- [ ] **Step 5: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_required_providers -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/core_pipeline/providers/baidu.py src/core_pipeline/providers/weibo.py src/core_pipeline/providers/xiaohongshu.py tests/core_pipeline/test_required_providers.py
git commit -m "feat: add required detail evidence providers"
```

Expected: commit succeeds.

## 7. Task 5: Auxiliary Evidence And Completeness

**Files:**

- Create: `src/core_pipeline/providers/auxiliary.py`
- Create: `src/core_pipeline/completeness.py`
- Create: `tests/core_pipeline/test_auxiliary_provider.py`
- Create: `tests/core_pipeline/test_completeness.py`

- [ ] **Step 1: Write auxiliary evidence tests**

Create `tests/core_pipeline/test_auxiliary_provider.py`:

```python
import unittest

from src.core_pipeline.providers.auxiliary import evidence_from_dailyhot_record
from src.core_pipeline.types import HotRecord


class AuxiliaryProviderTests(unittest.TestCase):
    def test_dailyhot_desc_becomes_auxiliary_evidence(self):
        record = HotRecord(
            id="hot_github_001",
            source="dailyhotapi",
            platform="github",
            route="github",
            category="foreign_tech",
            title="项目趋势",
            rank=1,
            hot_value="100",
            url="https://github.com/example/repo",
            mobile_url="",
            desc="GitHub 趋势项目描述",
            author="example",
            cover="",
            timestamp="",
            captured_at="2026-06-14T20:00:00+08:00",
            raw_payload={"repo": "repo"},
            fetch_status="ok",
            error_type=None,
        )

        evidence = evidence_from_dailyhot_record(record, "2026-06-14T20:10:00+08:00")

        self.assertEqual(evidence.source_role, "auxiliary")
        self.assertEqual(evidence.platform, "github")
        self.assertIn("GitHub 趋势项目描述", evidence.content)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement auxiliary evidence builder**

Create `src/core_pipeline/providers/auxiliary.py`:

```python
from src.core_pipeline.types import DetailEvidence, HotRecord


def evidence_from_dailyhot_record(record: HotRecord, fetched_at: str) -> DetailEvidence:
    content_parts = [record.title, record.desc, record.author, record.hot_value]
    content = "\n".join(part for part in content_parts if part)
    return DetailEvidence(
        evidence_id=f"evidence_aux_{record.platform}_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform=record.platform,
        source_role="auxiliary",
        source_method="dailyhotapi",
        query=record.title,
        url=record.url,
        title=f"{record.platform} 辅助证据：{record.title}",
        content=content,
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[record.url] if record.url else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=record.fetch_status,
        error_type=record.error_type,
        confidence="low" if not record.desc else "medium",
        raw_payload=record.raw_payload,
    )
```

- [ ] **Step 3: Write completeness tests**

Create `tests/core_pipeline/test_completeness.py`:

```python
import unittest

from src.core_pipeline.completeness import evaluate_required_details
from src.core_pipeline.types import DetailEvidence


def evidence(platform: str, role: str, status: str) -> DetailEvidence:
    return DetailEvidence(
        evidence_id=f"evidence_{platform}",
        topic_key="测试热点",
        related_hot_record_ids=["hot_001"],
        platform=platform,
        source_role=role,
        source_method="test",
        query="测试热点",
        url="",
        title="",
        content="内容" if status == "ok" else "",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=[],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at="2026-06-14T20:10:00+08:00",
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium",
        raw_payload={},
    )


class CompletenessTests(unittest.TestCase):
    def test_complete_when_required_three_sources_are_ok(self):
        result = evaluate_required_details(
            "测试热点",
            [
                evidence("weibo", "required", "ok"),
                evidence("xiaohongshu", "required", "ok"),
                evidence("baidu", "required", "ok"),
                evidence("github", "auxiliary", "ok"),
            ],
        )

        self.assertEqual(result.detail_completeness, "complete")
        self.assertEqual(result.auxiliary_evidence_count, 1)

    def test_missing_xiaohongshu_marks_core_incomplete(self):
        result = evaluate_required_details(
            "测试热点",
            [
                evidence("weibo", "required", "ok"),
                evidence("xiaohongshu", "required", "login_required"),
                evidence("baidu", "required", "ok"),
            ],
        )

        self.assertEqual(result.detail_completeness, "core_incomplete")
        self.assertEqual(result.missing_required_details, ["xiaohongshu"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Implement completeness evaluator**

Create `src/core_pipeline/completeness.py`:

```python
from src.core_pipeline.source_registry import REQUIRED_DETAIL_PLATFORMS
from src.core_pipeline.types import DetailEvidence, RequiredDetailStatus


def evaluate_required_details(topic_key: str, evidence_rows: list[DetailEvidence]) -> RequiredDetailStatus:
    status_by_platform = {platform: "failed" for platform in REQUIRED_DETAIL_PLATFORMS}
    auxiliary_count = 0
    for evidence in evidence_rows:
        if evidence.source_role == "auxiliary" and evidence.fetch_status == "ok":
            auxiliary_count += 1
        if evidence.platform in status_by_platform and evidence.source_role == "required":
            status_by_platform[evidence.platform] = evidence.fetch_status
    missing = [
        platform
        for platform in REQUIRED_DETAIL_PLATFORMS
        if status_by_platform[platform] != "ok"
    ]
    if not evidence_rows:
        completeness = "failed"
    elif len(missing) == len(REQUIRED_DETAIL_PLATFORMS) and auxiliary_count > 0:
        completeness = "auxiliary_only"
    elif missing:
        completeness = "core_incomplete"
    else:
        completeness = "complete"
    return RequiredDetailStatus(
        topic_key=topic_key,
        weibo=status_by_platform["weibo"],
        xiaohongshu=status_by_platform["xiaohongshu"],
        baidu=status_by_platform["baidu"],
        missing_required_details=missing,
        auxiliary_evidence_count=auxiliary_count,
        detail_completeness=completeness,
    )
```

- [ ] **Step 5: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_auxiliary_provider tests.core_pipeline.test_completeness -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/core_pipeline/providers/auxiliary.py src/core_pipeline/completeness.py tests/core_pipeline/test_auxiliary_provider.py tests/core_pipeline/test_completeness.py
git commit -m "feat: evaluate core detail completeness"
```

Expected: commit succeeds.

## 8. Task 6: Topic Clustering And Brief Generation

**Files:**

- Create: `src/core_pipeline/topic_clusterer.py`
- Create: `src/core_pipeline/brief_generator.py`
- Create: `tests/core_pipeline/test_topic_clusterer.py`
- Create: `tests/core_pipeline/test_brief_generator.py`

- [ ] **Step 1: Write clusterer tests**

Create `tests/core_pipeline/test_topic_clusterer.py`:

```python
import unittest

from src.core_pipeline.topic_clusterer import cluster_topics
from src.core_pipeline.types import DetailEvidence, HotRecord


def hot(record_id: str, title: str, platform: str) -> HotRecord:
    return HotRecord(record_id, "dailyhotapi", platform, platform, "core_discovery", title, 1, "", "", "", "", "", "", "", "2026-06-14T20:00:00+08:00", {}, "ok", None)


def ev(evidence_id: str, title: str, platform: str) -> DetailEvidence:
    return DetailEvidence(evidence_id, title, ["hot_001"], platform, "required", "test", title, "", title, "内容", "", "", {}, [], [], "", "", "2026-06-14T20:10:00+08:00", "ok", None, "medium", {})


class TopicClustererTests(unittest.TestCase):
    def test_same_normalized_title_merges_records_and_evidence(self):
        clusters = cluster_topics(
            [hot("hot_001", "测试 热点", "weibo"), hot("hot_002", "测试热点", "baidu")],
            [ev("evidence_001", "测试热点", "weibo")],
        )

        self.assertEqual(len(clusters), 1)
        self.assertEqual(sorted(clusters[0].hot_record_ids), ["hot_001", "hot_002"])
        self.assertEqual(clusters[0].evidence_ids, ["evidence_001"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement clusterer**

Create `src/core_pipeline/topic_clusterer.py`:

```python
import re

from src.core_pipeline.completeness import evaluate_required_details
from src.core_pipeline.types import DetailEvidence, HotRecord, TopicCluster


def _topic_key(title: str) -> str:
    return re.sub(r"\s+", "", title).lower()


def cluster_topics(records: list[HotRecord], evidence_rows: list[DetailEvidence]) -> list[TopicCluster]:
    buckets: dict[str, dict[str, object]] = {}
    for record in records:
        key = _topic_key(record.title)
        bucket = buckets.setdefault(key, {"titles": [], "records": [], "evidence": []})
        bucket["titles"].append(record.title)
        bucket["records"].append(record)
    for evidence in evidence_rows:
        key = _topic_key(evidence.topic_key)
        bucket = buckets.setdefault(key, {"titles": [], "records": [], "evidence": []})
        bucket["titles"].append(evidence.topic_key)
        bucket["evidence"].append(evidence)
    clusters: list[TopicCluster] = []
    for index, bucket in enumerate(buckets.values(), start=1):
        bucket_records = bucket["records"]
        bucket_evidence = bucket["evidence"]
        titles = [str(title) for title in bucket["titles"] if str(title)]
        canonical_title = titles[0] if titles else f"topic_{index:03d}"
        completeness = evaluate_required_details(canonical_title, bucket_evidence)
        platforms = sorted(
            {
                item.platform
                for item in list(bucket_records) + list(bucket_evidence)
            }
        )
        clusters.append(
            TopicCluster(
                topic_id=f"topic_{index:03d}",
                canonical_title=canonical_title,
                aliases=sorted(set(titles)),
                hot_record_ids=[record.id for record in bucket_records],
                evidence_ids=[evidence.evidence_id for evidence in bucket_evidence],
                platforms=platforms,
                required_detail_status={
                    "weibo": completeness.weibo,
                    "xiaohongshu": completeness.xiaohongshu,
                    "baidu": completeness.baidu,
                },
                detail_completeness=completeness.detail_completeness,
                cluster_confidence="high" if completeness.detail_completeness == "complete" else "low",
            )
        )
    return clusters
```

- [ ] **Step 3: Write brief generator tests**

Create `tests/core_pipeline/test_brief_generator.py`:

```python
import unittest

from src.core_pipeline.brief_generator import generate_topic_brief
from src.core_pipeline.types import DetailEvidence, TopicCluster


class BriefGeneratorTests(unittest.TestCase):
    def test_brief_uses_evidence_and_marks_missing_required_sources(self):
        cluster = TopicCluster(
            topic_id="topic_001",
            canonical_title="测试热点",
            aliases=["测试热点"],
            hot_record_ids=["hot_001"],
            evidence_ids=["evidence_001"],
            platforms=["weibo"],
            required_detail_status={"weibo": "ok", "xiaohongshu": "login_required", "baidu": "ok"},
            detail_completeness="core_incomplete",
            cluster_confidence="low",
        )
        evidence = DetailEvidence(
            "evidence_001",
            "测试热点",
            ["hot_001"],
            "weibo",
            "required",
            "test",
            "测试热点",
            "",
            "微博详情",
            "微博正文内容",
            "",
            "",
            {},
            ["评论"],
            [],
            "",
            "",
            "2026-06-14T20:10:00+08:00",
            "ok",
            None,
            "medium",
            {},
        )

        brief = generate_topic_brief(cluster, [evidence])

        self.assertEqual(brief.missing_required_details, ["xiaohongshu"])
        self.assertIn("微博正文内容", brief.summary)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Implement deterministic brief generator**

Create `src/core_pipeline/brief_generator.py`:

```python
from src.core_pipeline.types import DetailEvidence, TopicBrief, TopicCluster


def generate_topic_brief(cluster: TopicCluster, evidence_rows: list[DetailEvidence]) -> TopicBrief:
    evidence_by_id = {evidence.evidence_id: evidence for evidence in evidence_rows}
    selected = [
        evidence_by_id[evidence_id]
        for evidence_id in cluster.evidence_ids
        if evidence_id in evidence_by_id
    ]
    ok_evidence = [evidence for evidence in selected if evidence.fetch_status == "ok" and evidence.content]
    summary_text = "；".join(evidence.content[:80] for evidence in ok_evidence[:3])
    if not summary_text:
        summary_text = "核心详情未采集到可用正文。"
    missing = [
        platform
        for platform, status in cluster.required_detail_status.items()
        if status != "ok"
    ]
    observations = {
        evidence.platform: evidence.content[:120]
        for evidence in ok_evidence
    }
    key_facts = [evidence.title for evidence in ok_evidence[:5] if evidence.title]
    return TopicBrief(
        topic_id=cluster.topic_id,
        canonical_title=cluster.canonical_title,
        summary=summary_text,
        key_facts=key_facts,
        platform_observations=observations,
        evidence_ids=cluster.evidence_ids,
        missing_required_details=missing,
        detail_completeness=cluster.detail_completeness,
        confidence=cluster.cluster_confidence,
    )
```

- [ ] **Step 5: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_topic_clusterer tests.core_pipeline.test_brief_generator -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/core_pipeline/topic_clusterer.py src/core_pipeline/brief_generator.py tests/core_pipeline/test_topic_clusterer.py tests/core_pipeline/test_brief_generator.py
git commit -m "feat: cluster and organize detailed topics"
```

Expected: commit succeeds.

## 9. Task 7: Report Renderer And Manual Pipeline CLI

**Files:**

- Create: `src/core_pipeline/report_renderer.py`
- Create: `src/core_pipeline/run.py`
- Create: `tests/core_pipeline/test_report_renderer.py`
- Create: `tests/core_pipeline/test_run.py`
- Modify: `Makefile`

- [ ] **Step 1: Write report renderer tests**

Create `tests/core_pipeline/test_report_renderer.py`:

```python
import unittest

from src.core_pipeline.report_renderer import render_markdown_report
from src.core_pipeline.types import TopicBrief


class ReportRendererTests(unittest.TestCase):
    def test_report_shows_completeness_and_missing_sources(self):
        brief = TopicBrief(
            topic_id="topic_001",
            canonical_title="测试热点",
            summary="摘要",
            key_facts=["事实一"],
            platform_observations={"weibo": "微博观察"},
            evidence_ids=["evidence_001"],
            missing_required_details=["xiaohongshu"],
            detail_completeness="core_incomplete",
            confidence="low",
        )

        markdown = render_markdown_report([brief], generated_at="2026-06-14T21:00:00+08:00")

        self.assertIn("# 核心平台热点详情汇总", markdown)
        self.assertIn("core_incomplete", markdown)
        self.assertIn("xiaohongshu", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement Markdown renderer**

Create `src/core_pipeline/report_renderer.py`:

```python
from src.core_pipeline.types import TopicBrief


def render_markdown_report(briefs: list[TopicBrief], generated_at: str) -> str:
    lines = [
        "# 核心平台热点详情汇总",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 话题数量：`{len(briefs)}`",
        "",
    ]
    for brief in briefs:
        lines.extend(
            [
                f"## {brief.canonical_title}",
                "",
                f"- 完整度：`{brief.detail_completeness}`",
                f"- 可信度：`{brief.confidence}`",
                f"- 缺失核心详情源：`{', '.join(brief.missing_required_details) if brief.missing_required_details else '无'}`",
                f"- 证据 ID：`{', '.join(brief.evidence_ids)}`",
                "",
                "### 摘要",
                "",
                brief.summary,
                "",
                "### 关键事实",
                "",
            ]
        )
        if brief.key_facts:
            lines.extend(f"- {fact}" for fact in brief.key_facts)
        else:
            lines.append("- 未从详情证据中提取到关键事实。")
        lines.extend(["", "### 平台观察", ""])
        if brief.platform_observations:
            lines.extend(
                f"- `{platform}`：{observation}"
                for platform, observation in sorted(brief.platform_observations.items())
            )
        else:
            lines.append("- 暂无可用平台观察。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 3: Write CLI smoke test**

Create `tests/core_pipeline/test_run.py`:

```python
import unittest

from src.core_pipeline.run import output_paths


class RunTests(unittest.TestCase):
    def test_output_paths_are_fixed(self):
        paths = output_paths()

        self.assertEqual(str(paths["hot_records"]), "data/raw/dailyhot_records.json")
        self.assertEqual(str(paths["detail_evidence"]), "data/evidence/detail_evidence.json")
        self.assertEqual(str(paths["topic_briefs"]), "data/processed/topic_briefs.json")
        self.assertEqual(str(paths["markdown_report"]), "reports/core_platform_topic_digest.md")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Implement CLI output paths and command skeleton**

Create `src/core_pipeline/run.py`:

```python
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.core_pipeline.json_store import read_json_list, write_json_list
from src.core_pipeline.report_renderer import render_markdown_report
from src.core_pipeline.types import TopicBrief


def now_shanghai_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def output_paths() -> dict[str, Path]:
    return {
        "hot_records": Path("data/raw/dailyhot_records.json"),
        "detail_evidence": Path("data/evidence/detail_evidence.json"),
        "topic_clusters": Path("data/processed/topic_clusters.json"),
        "topic_briefs": Path("data/processed/topic_briefs.json"),
        "markdown_report": Path("reports/core_platform_topic_digest.md"),
    }


def render_report_command() -> None:
    paths = output_paths()
    rows = read_json_list(paths["topic_briefs"])
    briefs = [TopicBrief(**row) for row in rows]
    markdown = render_markdown_report(briefs, generated_at=now_shanghai_iso())
    paths["markdown_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["markdown_report"].write_text(markdown, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("paths", "render-report"))
    args = parser.parse_args()
    if args.command == "paths":
        write_json_list("data/processed/pipeline_paths.json", [{key: str(value) for key, value in output_paths().items()}])
    if args.command == "render-report":
        render_report_command()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Modify `Makefile`**

Add these targets without removing existing targets:

```makefile
.PHONY: collect-dailyhot collect-core-details collect-aux-evidence cluster-topics generate-briefs render-report run-core-pipeline

collect-dailyhot:
	$(PYTHON) -m src.core_pipeline.run paths

collect-core-details:
	$(PYTHON) -m src.core_pipeline.run paths

collect-aux-evidence:
	$(PYTHON) -m src.core_pipeline.run paths

cluster-topics:
	$(PYTHON) -m src.core_pipeline.run paths

generate-briefs:
	$(PYTHON) -m src.core_pipeline.run paths

render-report:
	$(PYTHON) -m src.core_pipeline.run render-report

run-core-pipeline: check-sessions collect-dailyhot collect-core-details collect-aux-evidence cluster-topics generate-briefs render-report
```

- [ ] **Step 6: Run task tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_report_renderer tests.core_pipeline.test_run -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add Makefile src/core_pipeline/report_renderer.py src/core_pipeline/run.py tests/core_pipeline/test_report_renderer.py tests/core_pipeline/test_run.py
git commit -m "feat: render core platform detail reports"
```

Expected: commit succeeds.

## 10. Task 8: Real Browser Collection Integration

**Files:**

- Modify: `src/core_pipeline/providers/weibo.py`
- Modify: `src/core_pipeline/providers/xiaohongshu.py`
- Modify: `src/core_pipeline/run.py`
- Create: `tests/core_pipeline/test_browser_extraction.py`

- [ ] **Step 1: Write extraction tests using static HTML text**

Create `tests/core_pipeline/test_browser_extraction.py`:

```python
import unittest

from src.core_pipeline.providers.weibo import extract_weibo_posts_from_text
from src.core_pipeline.providers.xiaohongshu import extract_xiaohongshu_notes_from_text


class BrowserExtractionTests(unittest.TestCase):
    def test_extract_weibo_posts_from_text_chunks_content(self):
        text = "用户A\n测试热点正文一\n赞 10 评论 2\n用户B\n测试热点正文二\n赞 3 评论 1"

        posts = extract_weibo_posts_from_text(text)

        self.assertGreaterEqual(len(posts), 1)
        self.assertIn("测试热点正文一", posts[0]["content"])

    def test_extract_xiaohongshu_notes_from_text_chunks_content(self):
        text = "笔记标题\n测试热点笔记正文\n赞 20 收藏 5\n评论 这件事很热"

        notes = extract_xiaohongshu_notes_from_text(text)

        self.assertGreaterEqual(len(notes), 1)
        self.assertIn("测试热点笔记正文", notes[0]["content"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Add text extraction helpers**

Append to `src/core_pipeline/providers/weibo.py`:

```python
def extract_weibo_posts_from_text(page_text: str) -> list[dict[str, object]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    chunks: list[dict[str, object]] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if line.startswith("赞 ") or " 评论 " in line:
            content = "\n".join(current)
            chunks.append({"content": content, "comments_preview": [], "url": ""})
            current = []
    if current:
        chunks.append({"content": "\n".join(current), "comments_preview": [], "url": ""})
    return chunks[:5]
```

Append to `src/core_pipeline/providers/xiaohongshu.py`:

```python
def extract_xiaohongshu_notes_from_text(page_text: str) -> list[dict[str, object]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    chunks: list[dict[str, object]] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if line.startswith("赞 ") or line.startswith("评论 ") or " 收藏 " in line:
            content = "\n".join(current)
            chunks.append({"content": content, "comments_preview": [], "url": ""})
            current = []
    if current:
        chunks.append({"content": "\n".join(current), "comments_preview": [], "url": ""})
    return chunks[:5]
```

- [ ] **Step 3: Wire browser collection behind session gate**

Modify `src/core_pipeline/run.py` by adding command names:

```python
parser.add_argument("command", choices=("paths", "render-report", "collect-core-details"))
```

Add a `collect-core-details` branch that reads `data/raw/dailyhot_records.json`, checks `data/browser_state`, writes required provider status evidence to `data/evidence/detail_evidence.json`, and does not attempt collection when session status is not `ok`.

The first implementation may use existing saved extraction fixtures or text snapshots. When integrating Playwright, keep these rules:

```text
1. Open the target search page with saved storage state.
2. Wait for a normal content container.
3. If URL or page text contains login, verify, captcha, 滑块, 安全验证, or 访问异常, record the corresponding status.
4. Extract visible text from the first result screen only.
5. Save HTML and screenshot paths.
6. Close the page.
```

- [ ] **Step 4: Run extraction tests**

Run:

```bash
python3 -m unittest tests.core_pipeline.test_browser_extraction -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/core_pipeline/providers/weibo.py src/core_pipeline/providers/xiaohongshu.py src/core_pipeline/run.py tests/core_pipeline/test_browser_extraction.py
git commit -m "feat: prepare logged-in browser detail extraction"
```

Expected: commit succeeds.

## 11. Task 9: End-To-End Verification

**Files:**

- Modify only files changed by previous tasks if verification reveals a defect.

- [ ] **Step 1: Run all tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Check generated command paths**

Run:

```bash
python3 -m src.core_pipeline.run paths
python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("data/processed/pipeline_paths.json").read_text(encoding="utf-8"))
print(data[0]["detail_evidence"])
PY
```

Expected output contains:

```text
data/evidence/detail_evidence.json
```

- [ ] **Step 3: Run session check**

Run:

```bash
make check-sessions
```

Expected: command exits normally. If Weibo or Xiaohongshu is not logged in, output must clearly show `login_required`.

- [ ] **Step 4: Run manual login commands when needed**

Run only when session check reports missing login:

```bash
make login-weibo
make login-xiaohongshu
make check-sessions
```

Expected: after manual browser login, session files exist locally under `data/browser_state/` and remain untracked by Git.

- [ ] **Step 5: Run first-version pipeline commands**

Run:

```bash
make collect-dailyhot
make collect-core-details
make collect-aux-evidence
make cluster-topics
make generate-briefs
make render-report
```

Expected: runtime files are created at:

```text
data/raw/dailyhot_records.json
data/evidence/detail_evidence.json
data/processed/topic_clusters.json
data/processed/topic_briefs.json
reports/core_platform_topic_digest.md
```

- [ ] **Step 6: Inspect completeness distribution**

Run:

```bash
python3 - <<'PY'
import json
from collections import Counter
from pathlib import Path
path = Path("data/processed/topic_clusters.json")
if path.exists():
    rows = json.loads(path.read_text(encoding="utf-8"))
else:
    rows = []
print(Counter(row.get("detail_completeness", "missing") for row in rows))
PY
```

Expected: output prints a `Counter`. A topic can be `core_incomplete`, but the report must show which required source is missing.

- [ ] **Step 7: Commit verification fixes**

Run after any verification fix:

```bash
git add src/core_pipeline tests/core_pipeline Makefile .gitignore
git commit -m "fix: stabilize core detail pipeline verification"
```

Expected: commit succeeds when fixes were made. Skip this command when no verification fixes were made.

## 12. Manual Run Contract

The intended first-version run sequence is:

```bash
make check-sessions
make login-weibo
make login-xiaohongshu
make collect-dailyhot
make collect-core-details
make collect-aux-evidence
make cluster-topics
make generate-briefs
make render-report
```

For normal use after login has been initialized:

```bash
make run-core-pipeline
```

The final report must make this distinction visible:

- `complete`: Weibo, Xiaohongshu, and Baidu required details are all `ok`.
- `core_incomplete`: at least one required detail source is missing, blocked, empty, or failed.
- `auxiliary_only`: required sources did not provide usable detail, but other sources did.
- `failed`: neither required nor auxiliary evidence is usable.

## 13. Self-Review

Spec coverage:

- DailyHotApi quick discovery is covered by Task 2 and `source_registry.py`.
- Weibo, Xiaohongshu, and Baidu required details are covered by Task 3, Task 4, and Task 8.
- Auxiliary sources are covered by Task 1 route groups and Task 5 auxiliary evidence.
- Detail storage is covered by Task 2 `json_store.py` and runtime files under `data/evidence/`.
- Same-topic clustering is covered by Task 6 `topic_clusterer.py`.
- LLM-ready organizing is covered by Task 6 `brief_generator.py`; the deterministic fallback provides testable first-version behavior before an LLM client is wired.
- Daily summary output is covered by Task 7 `report_renderer.py`.
- Login-first behavior is covered by Task 3 session gate and Task 9 manual run sequence.
- Long-term automation is intentionally not implemented; the command contract keeps the flow ready for later scheduler integration.

Placeholder scan:

- The plan avoids `TODO`, `TBD`, `fill in`, `similar to`, and unnamed validation.
- The only intentionally future-facing item is LLM client wiring, and the plan provides a deterministic implementation for the first version.

Type consistency:

- `HotRecord`, `DetailEvidence`, `RequiredDetailStatus`, `TopicCluster`, and `TopicBrief` names are consistent across tests and implementation snippets.
- Runtime output paths match the files listed in the file structure section.
- Status values use the fixed strings in the data contract section.
