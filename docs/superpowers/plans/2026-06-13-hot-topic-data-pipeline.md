# Hot Topic Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manually-run hot topic data pipeline that collects DailyHotApi hot records, gathers detailed platform information from Weibo/Baidu/Xiaohongshu providers, stores details separately, clusters related topics with an LLM-ready interface, and renders JSON plus Markdown outputs.

**Architecture:** Keep the first version file-based and testable with standard-library `unittest`. Separate the pipeline into focused modules: schemas, JSON stores, DailyHot collection, browser session checks, platform detail providers, clustering, summarization, and report rendering. Browser providers must check login state before platform collection and must record failures instead of bypassing captcha or rate limits.

**Tech Stack:** Python 3.10+ standard library, existing `urllib.request`, optional Playwright for real browser login/collection commands, JSON files for first-version storage, Makefile command entry points, Markdown reports.

---

## File Structure

Create these new modules:

- `src/pipeline_config.py`: shared paths, platform lists, limits, and private browser-state paths.
- `src/details/detail_types.py`: dataclasses for `PipelineHotRecord`, `PlatformDetail`, `TopicCluster`, `TopicBrief`, and error/status constants.
- `src/details/detail_store.py`: JSON read/write helpers for hot records, platform details, topic clusters, and topic briefs.
- `src/collectors/daily_hot_collector.py`: converts existing DailyHotApi records into first-version `PipelineHotRecord` objects with category and IDs.
- `src/browser/session_manager.py`: checks browser session files, reports login requirements, and provides login command scaffolding.
- `src/browser/page_guards.py`: platform guard result helpers for `login_required`, `captcha_required`, `rate_limited`, `layout_changed`, and `ok`.
- `src/collectors/weibo_provider.py`: Weibo detail provider interface with safe session checks and deterministic fallback detail records.
- `src/collectors/baidu_provider.py`: Baidu search/detail provider interface with search-result detail records.
- `src/collectors/xiaohongshu_provider.py`: Xiaohongshu detail provider interface with safe session checks and deterministic fallback detail records.
- `src/clustering/topic_clusterer.py`: rule-based pre-clustering and LLM-ready cluster output.
- `src/summarization/topic_brief_generator.py`: LLM-ready brief generation with deterministic fallback.
- `src/reports/daily_digest_renderer.py`: Markdown renderer for the new daily topic digest.
- `src/run_pipeline.py`: orchestrates the manual first-version pipeline.

Modify these existing files:

- `Makefile`: add `check-sessions`, `login-weibo`, `login-xiaohongshu`, `collect-hot`, `collect-details`, `cluster-topics`, `generate-digest`, and `run-pipeline`.
- `.gitignore`: add local browser state, screenshots, snapshots, and generated first-version JSON paths if not already ignored.

Create these tests:

- `tests/test_detail_types.py`
- `tests/test_detail_store.py`
- `tests/test_daily_hot_collector.py`
- `tests/test_session_manager.py`
- `tests/test_platform_providers.py`
- `tests/test_topic_clusterer.py`
- `tests/test_topic_brief_generator.py`
- `tests/test_daily_digest_renderer.py`
- `tests/test_run_pipeline.py`

---

### Task 1: Pipeline Config And Data Schemas

**Files:**
- Create: `src/pipeline_config.py`
- Create: `src/details/detail_types.py`
- Create: `tests/test_detail_types.py`
- Modify: `src/details/__init__.py` if package file is needed

- [ ] **Step 1: Create package directory placeholders**

Run:

```bash
mkdir -p src/details tests
touch src/details/__init__.py
```

Expected: `src/details/__init__.py` exists.

- [ ] **Step 2: Write the failing schema tests**

Create `tests/test_detail_types.py`:

```python
import unittest

from src.details.detail_types import (
    FetchStatus,
    PlatformDetail,
    PipelineHotRecord,
    TopicBrief,
    TopicCluster,
)


class DetailTypesTests(unittest.TestCase):
    def test_pipeline_hot_record_to_dict_contains_category_and_status(self):
        record = PipelineHotRecord(
            id="hot_001",
            source="dailyhotapi",
            platform="weibo",
            category="domestic_social",
            title="测试热点",
            rank=1,
            hot_value="1000",
            url="https://example.com",
            captured_at="2026-06-13 20:00:00",
            raw_payload={"title": "测试热点"},
            fetch_status=FetchStatus.OK,
            error=None,
        )

        data = record.to_dict()

        self.assertEqual(data["id"], "hot_001")
        self.assertEqual(data["category"], "domestic_social")
        self.assertEqual(data["fetch_status"], "ok")
        self.assertEqual(data["raw_payload"], {"title": "测试热点"})

    def test_platform_detail_to_dict_preserves_detail_content(self):
        detail = PlatformDetail(
            detail_id="detail_001",
            related_hot_record_ids=["hot_001"],
            platform="weibo",
            source_method="browser_session",
            query="测试热点",
            url="https://example.com/post",
            title="微博详情",
            content="微博正文内容",
            author="作者",
            published_at="2026-06-13 18:20:00",
            metrics={"likes": 12, "comments": 3},
            comments_preview=["评论一"],
            result_urls=[],
            raw_snapshot_path="data/snapshots/weibo/detail_001.html",
            screenshot_path="data/screenshots/weibo/detail_001.png",
            fetched_at="2026-06-13 20:10:00",
            fetch_status=FetchStatus.OK,
            error_type=None,
            confidence="medium",
        )

        data = detail.to_dict()

        self.assertEqual(data["content"], "微博正文内容")
        self.assertEqual(data["comments_preview"], ["评论一"])
        self.assertEqual(data["metrics"]["likes"], 12)

    def test_topic_cluster_and_brief_to_dict_are_traceable(self):
        cluster = TopicCluster(
            topic_id="topic_001",
            canonical_title="测试事件",
            aliases=["测试热点"],
            platforms=["weibo", "baidu"],
            hot_record_ids=["hot_001"],
            detail_ids=["detail_001"],
            merge_reason="标题和详情都指向同一事件。",
            cluster_confidence="high",
        )
        brief = TopicBrief(
            topic_id="topic_001",
            canonical_title="测试事件",
            summary="测试事件引发跨平台讨论。",
            key_facts=["事实一"],
            platform_discussion={"weibo": "微博讨论争议点。"},
            timeline=[{"time": "2026-06-13", "event": "事件出现"}],
            source_evidence=[
                {
                    "detail_id": "detail_001",
                    "platform": "weibo",
                    "evidence": "正文片段",
                    "confidence": "medium",
                }
            ],
            open_questions=["是否有官方回应。"],
            confidence="medium",
        )

        self.assertEqual(cluster.to_dict()["detail_ids"], ["detail_001"])
        self.assertEqual(brief.to_dict()["source_evidence"][0]["detail_id"], "detail_001")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run schema tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_detail_types -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `src.details.detail_types`.

- [ ] **Step 4: Implement pipeline config**

Create `src/pipeline_config.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"

RAW_DATA_DIR = DATA_DIR / "raw"
DETAILS_DATA_DIR = DATA_DIR / "details"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
BROWSER_STATE_DIR = DATA_DIR / "browser_state"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"

HOT_RECORDS_PATH = RAW_DATA_DIR / "hot_records.json"
PLATFORM_DETAILS_PATH = DETAILS_DATA_DIR / "platform_details.json"
TOPIC_CLUSTERS_PATH = PROCESSED_DATA_DIR / "topic_clusters.json"
TOPIC_BRIEFS_PATH = PROCESSED_DATA_DIR / "topic_briefs.json"
DAILY_TOPIC_DIGEST_PATH = REPORTS_DIR / "daily_topic_digest.md"

WEIBO_STATE_PATH = BROWSER_STATE_DIR / "weibo.json"
XIAOHONGSHU_STATE_PATH = BROWSER_STATE_DIR / "xiaohongshu.json"

DAILY_HOT_PLATFORM_CATEGORIES = {
    "weibo": "domestic_social",
    "baidu": "domestic_search",
    "zhihu": "domestic_social",
    "bilibili": "domestic_video",
    "36kr": "domestic_business",
    "ithome": "domestic_tech",
    "juejin": "domestic_tech",
    "csdn": "domestic_tech",
    "github": "global_tech",
    "v2ex": "global_tech",
    "hellogithub": "global_tech",
    "producthunt": "global_tech",
    "hackernews": "global_tech",
}

DAILY_HOT_PLATFORMS = list(DAILY_HOT_PLATFORM_CATEGORIES.keys())

MAX_CANDIDATE_TOPICS = 10
MAX_WEIBO_DETAILS_PER_TOPIC = 5
MAX_XIAOHONGSHU_DETAILS_PER_TOPIC = 5
MAX_BAIDU_RESULTS_PER_TOPIC = 5
```

- [ ] **Step 5: Implement detail dataclasses**

Create `src/details/detail_types.py`:

```python
from dataclasses import dataclass, field
from typing import Any


class FetchStatus:
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PipelineHotRecord:
    id: str
    source: str
    platform: str
    category: str
    title: str
    rank: int | None
    hot_value: str
    url: str
    captured_at: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    fetch_status: str = FetchStatus.OK
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "platform": self.platform,
            "category": self.category,
            "title": self.title,
            "rank": self.rank,
            "hot_value": self.hot_value,
            "url": self.url,
            "captured_at": self.captured_at,
            "raw_payload": self.raw_payload,
            "fetch_status": self.fetch_status,
            "error": self.error,
        }


@dataclass(frozen=True)
class PlatformDetail:
    detail_id: str
    related_hot_record_ids: list[str]
    platform: str
    source_method: str
    query: str
    url: str
    title: str
    content: str
    author: str
    published_at: str
    metrics: dict[str, Any] = field(default_factory=dict)
    comments_preview: list[str] = field(default_factory=list)
    result_urls: list[str] = field(default_factory=list)
    raw_snapshot_path: str = ""
    screenshot_path: str = ""
    fetched_at: str = ""
    fetch_status: str = FetchStatus.OK
    error_type: str | None = None
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail_id": self.detail_id,
            "related_hot_record_ids": self.related_hot_record_ids,
            "platform": self.platform,
            "source_method": self.source_method,
            "query": self.query,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "published_at": self.published_at,
            "metrics": self.metrics,
            "comments_preview": self.comments_preview,
            "result_urls": self.result_urls,
            "raw_snapshot_path": self.raw_snapshot_path,
            "screenshot_path": self.screenshot_path,
            "fetched_at": self.fetched_at,
            "fetch_status": self.fetch_status,
            "error_type": self.error_type,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TopicCluster:
    topic_id: str
    canonical_title: str
    aliases: list[str]
    platforms: list[str]
    hot_record_ids: list[str]
    detail_ids: list[str]
    merge_reason: str
    cluster_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "canonical_title": self.canonical_title,
            "aliases": self.aliases,
            "platforms": self.platforms,
            "hot_record_ids": self.hot_record_ids,
            "detail_ids": self.detail_ids,
            "merge_reason": self.merge_reason,
            "cluster_confidence": self.cluster_confidence,
        }


@dataclass(frozen=True)
class TopicBrief:
    topic_id: str
    canonical_title: str
    summary: str
    key_facts: list[str]
    platform_discussion: dict[str, str]
    timeline: list[dict[str, str]]
    source_evidence: list[dict[str, str]]
    open_questions: list[str]
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "canonical_title": self.canonical_title,
            "summary": self.summary,
            "key_facts": self.key_facts,
            "platform_discussion": self.platform_discussion,
            "timeline": self.timeline,
            "source_evidence": self.source_evidence,
            "open_questions": self.open_questions,
            "confidence": self.confidence,
        }
```

- [ ] **Step 6: Run schema tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_detail_types -v
```

Expected: PASS with 3 tests.

- [ ] **Step 7: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all existing tests and new schema tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/pipeline_config.py src/details/__init__.py src/details/detail_types.py tests/test_detail_types.py
git commit -m "feat: add pipeline data schemas"
```

Expected: commit succeeds with only these files.

---

### Task 2: JSON Detail Store

**Files:**
- Create: `src/details/detail_store.py`
- Create: `tests/test_detail_store.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/test_detail_store.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from src.details.detail_store import (
    ensure_pipeline_dirs,
    read_json_list,
    write_json_list,
)


class DetailStoreTests(unittest.TestCase):
    def test_write_json_list_creates_parent_and_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "items.json"

            write_json_list(path, [{"title": "中文热点"}])

            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [{"title": "中文热点"}])
            self.assertIn("中文热点", path.read_text(encoding="utf-8"))

    def test_read_json_list_returns_empty_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"

            self.assertEqual(read_json_list(path), [])

    def test_ensure_pipeline_dirs_creates_expected_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            ensure_pipeline_dirs(root)

            self.assertTrue((root / "raw").is_dir())
            self.assertTrue((root / "details").is_dir())
            self.assertTrue((root / "processed").is_dir())
            self.assertTrue((root / "browser_state").is_dir())
            self.assertTrue((root / "snapshots" / "weibo").is_dir())
            self.assertTrue((root / "screenshots" / "xiaohongshu").is_dir())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run store tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_detail_store -v
```

Expected: FAIL with `ModuleNotFoundError` or missing functions.

- [ ] **Step 3: Implement JSON store helpers**

Create `src/details/detail_store.py`:

```python
import json
from pathlib import Path
from typing import Any


PLATFORM_DIRS = ("weibo", "baidu", "xiaohongshu")


def write_json_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected list JSON at {path}")
    return data


def ensure_pipeline_dirs(root: Path) -> None:
    for name in ("raw", "details", "processed", "browser_state"):
        (root / name).mkdir(parents=True, exist_ok=True)
    for platform in PLATFORM_DIRS:
        (root / "snapshots" / platform).mkdir(parents=True, exist_ok=True)
        (root / "screenshots" / platform).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run store tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_detail_store -v
```

Expected: PASS with 3 tests.

- [ ] **Step 5: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/details/detail_store.py tests/test_detail_store.py
git commit -m "feat: add pipeline JSON store"
```

Expected: commit succeeds.

---

### Task 3: DailyHotApi Pipeline Collector

**Files:**
- Create: `src/collectors/__init__.py`
- Create: `src/collectors/daily_hot_collector.py`
- Create: `tests/test_daily_hot_collector.py`

- [ ] **Step 1: Create collectors package**

Run:

```bash
mkdir -p src/collectors
touch src/collectors/__init__.py
```

Expected: `src/collectors/__init__.py` exists.

- [ ] **Step 2: Write failing collector tests**

Create `tests/test_daily_hot_collector.py`:

```python
import unittest

from src.collectors.daily_hot_collector import collect_daily_hot_records, normalize_daily_hot_records
from src.hot_topic_types import HotRecord


def hot_record(platform, rank, title, hot="1000", url="https://example.com"):
    return HotRecord(
        platform=platform,
        rank=rank,
        title=title,
        hot=hot,
        url=url,
        crawl_time="2026-06-13 20:00:00",
    )


class DailyHotCollectorTests(unittest.TestCase):
    def test_normalize_daily_hot_records_adds_ids_and_categories(self):
        records = [
            hot_record("weibo", 1, "微博热点"),
            hot_record("github", 2, "GitHub 热点", hot="500"),
        ]

        normalized = normalize_daily_hot_records(records)

        self.assertEqual(normalized[0].id, "hot_0001")
        self.assertEqual(normalized[0].category, "domestic_social")
        self.assertEqual(normalized[1].id, "hot_0002")
        self.assertEqual(normalized[1].category, "global_tech")
        self.assertEqual(normalized[1].hot_value, "500")

    def test_collect_daily_hot_records_uses_fetcher_and_platforms(self):
        def fake_fetcher(platforms, limit, return_issues):
            self.assertEqual(platforms, ["weibo", "baidu"])
            self.assertEqual(limit, 3)
            self.assertTrue(return_issues)
            return [hot_record("weibo", 1, "微博热点")], []

        normalized, issues = collect_daily_hot_records(
            platforms=["weibo", "baidu"],
            limit=3,
            fetcher=fake_fetcher,
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].title, "微博热点")
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run collector tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_daily_hot_collector -v
```

Expected: FAIL with missing module or functions.

- [ ] **Step 4: Implement DailyHot collector**

Create `src/collectors/daily_hot_collector.py`:

```python
from src.details.detail_types import PipelineHotRecord
from src.demo_config import TOP_N_PER_PLATFORM
from src.fetch_hot_lists import fetch_all_platforms
from src.hot_topic_types import HotRecord
from src.pipeline_config import DAILY_HOT_PLATFORM_CATEGORIES, DAILY_HOT_PLATFORMS


def normalize_daily_hot_records(records: list[HotRecord]) -> list[PipelineHotRecord]:
    normalized: list[PipelineHotRecord] = []
    for index, record in enumerate(records, start=1):
        normalized.append(
            PipelineHotRecord(
                id=f"hot_{index:04d}",
                source="dailyhotapi",
                platform=record.platform,
                category=DAILY_HOT_PLATFORM_CATEGORIES.get(record.platform, "other"),
                title=record.title,
                rank=record.rank,
                hot_value=record.hot,
                url=record.url,
                captured_at=record.crawl_time,
                raw_payload=record.to_dict(),
            )
        )
    return normalized


def collect_daily_hot_records(
    platforms: list[str] | None = None,
    limit: int = TOP_N_PER_PLATFORM,
    fetcher=fetch_all_platforms,
):
    selected_platforms = platforms or DAILY_HOT_PLATFORMS
    records, issues = fetcher(selected_platforms, limit, True)
    return normalize_daily_hot_records(records), issues
```

- [ ] **Step 5: Run collector tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_daily_hot_collector -v
```

Expected: PASS with 2 tests.

- [ ] **Step 6: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/collectors/__init__.py src/collectors/daily_hot_collector.py tests/test_daily_hot_collector.py
git commit -m "feat: collect pipeline hot records"
```

Expected: commit succeeds.

---

### Task 4: Browser Session Checks And Guards

**Files:**
- Create: `src/browser/__init__.py`
- Create: `src/browser/session_manager.py`
- Create: `src/browser/page_guards.py`
- Create: `tests/test_session_manager.py`

- [ ] **Step 1: Create browser package**

Run:

```bash
mkdir -p src/browser
touch src/browser/__init__.py
```

Expected: `src/browser/__init__.py` exists.

- [ ] **Step 2: Write failing session tests**

Create `tests/test_session_manager.py`:

```python
import tempfile
import unittest
from pathlib import Path

from src.browser.page_guards import classify_guard_text
from src.browser.session_manager import BrowserSessionStatus, check_required_sessions


class SessionManagerTests(unittest.TestCase):
    def test_check_required_sessions_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            statuses = check_required_sessions(
                {
                    "weibo": root / "weibo.json",
                    "xiaohongshu": root / "xiaohongshu.json",
                }
            )

            self.assertEqual(statuses["weibo"].status, BrowserSessionStatus.MISSING)
            self.assertEqual(statuses["xiaohongshu"].status, BrowserSessionStatus.MISSING)
            self.assertIn("make login-weibo", statuses["weibo"].message)

    def test_check_required_sessions_reports_ready_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weibo_state = root / "weibo.json"
            weibo_state.write_text('{"cookies":[]}', encoding="utf-8")

            statuses = check_required_sessions({"weibo": weibo_state})

            self.assertEqual(statuses["weibo"].status, BrowserSessionStatus.READY)

    def test_classify_guard_text_detects_login_and_captcha(self):
        self.assertEqual(classify_guard_text("请登录后继续访问"), "login_required")
        self.assertEqual(classify_guard_text("请完成验证码验证"), "captcha_required")
        self.assertEqual(classify_guard_text("访问过于频繁"), "rate_limited")
        self.assertEqual(classify_guard_text("正常页面内容"), "ok")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run session tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_session_manager -v
```

Expected: FAIL with missing modules or functions.

- [ ] **Step 4: Implement page guards**

Create `src/browser/page_guards.py`:

```python
GUARD_LOGIN = "login_required"
GUARD_CAPTCHA = "captcha_required"
GUARD_RATE_LIMITED = "rate_limited"
GUARD_LAYOUT_CHANGED = "layout_changed"
GUARD_OK = "ok"


def classify_guard_text(text: str) -> str:
    lowered = text.lower()
    if "登录" in text or "login" in lowered:
        return GUARD_LOGIN
    if "验证码" in text or "captcha" in lowered or "滑块" in text:
        return GUARD_CAPTCHA
    if "访问过于频繁" in text or "rate limit" in lowered or "too many requests" in lowered:
        return GUARD_RATE_LIMITED
    return GUARD_OK
```

- [ ] **Step 5: Implement session manager**

Create `src/browser/session_manager.py`:

```python
from dataclasses import dataclass
from pathlib import Path


class BrowserSessionStatus:
    READY = "ready"
    MISSING = "missing"


@dataclass(frozen=True)
class BrowserSessionCheck:
    platform: str
    path: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "path": self.path,
            "status": self.status,
            "message": self.message,
        }


def check_required_sessions(required: dict[str, Path]) -> dict[str, BrowserSessionCheck]:
    statuses: dict[str, BrowserSessionCheck] = {}
    for platform, path in required.items():
        if path.exists() and path.stat().st_size > 0:
            statuses[platform] = BrowserSessionCheck(
                platform=platform,
                path=str(path),
                status=BrowserSessionStatus.READY,
                message=f"{platform} browser session is ready.",
            )
        else:
            statuses[platform] = BrowserSessionCheck(
                platform=platform,
                path=str(path),
                status=BrowserSessionStatus.MISSING,
                message=f"{platform} browser session missing. Run make login-{platform}.",
            )
    return statuses
```

- [ ] **Step 6: Run session tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_session_manager -v
```

Expected: PASS with 3 tests.

- [ ] **Step 7: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/browser/__init__.py src/browser/page_guards.py src/browser/session_manager.py tests/test_session_manager.py
git commit -m "feat: add browser session checks"
```

Expected: commit succeeds.

---

### Task 5: Platform Detail Providers

**Files:**
- Create: `src/collectors/weibo_provider.py`
- Create: `src/collectors/baidu_provider.py`
- Create: `src/collectors/xiaohongshu_provider.py`
- Create: `tests/test_platform_providers.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/test_platform_providers.py`:

```python
import unittest

from src.collectors.baidu_provider import BaiduProvider
from src.collectors.weibo_provider import WeiboProvider
from src.collectors.xiaohongshu_provider import XiaohongshuProvider
from src.details.detail_types import FetchStatus, PipelineHotRecord


def hot_record(record_id, platform, title):
    return PipelineHotRecord(
        id=record_id,
        source="dailyhotapi",
        platform=platform,
        category="domestic_social",
        title=title,
        rank=1,
        hot_value="1000",
        url="https://example.com",
        captured_at="2026-06-13 20:00:00",
    )


class PlatformProvidersTests(unittest.TestCase):
    def test_weibo_provider_returns_login_required_when_session_missing(self):
        provider = WeiboProvider(session_ready=False)

        details = provider.collect_details([hot_record("hot_001", "weibo", "微博热点")])

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].fetch_status, FetchStatus.FAILED)
        self.assertEqual(details[0].error_type, "login_required")
        self.assertEqual(details[0].related_hot_record_ids, ["hot_001"])

    def test_baidu_provider_returns_search_detail_without_login(self):
        provider = BaiduProvider(searcher=lambda query: [{"title": "结果", "url": "https://news.example", "snippet": "摘要"}])

        details = provider.collect_details([hot_record("hot_002", "baidu", "百度热点")])

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].platform, "baidu")
        self.assertEqual(details[0].source_method, "search_api")
        self.assertEqual(details[0].content, "摘要")
        self.assertEqual(details[0].result_urls, ["https://news.example"])

    def test_xiaohongshu_provider_returns_login_required_when_session_missing(self):
        provider = XiaohongshuProvider(session_ready=False)

        details = provider.collect_details([hot_record("hot_003", "weibo", "小红书相关热点")])

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].platform, "xiaohongshu")
        self.assertEqual(details[0].fetch_status, FetchStatus.FAILED)
        self.assertEqual(details[0].error_type, "login_required")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run provider tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_platform_providers -v
```

Expected: FAIL with missing provider modules.

- [ ] **Step 3: Implement Weibo provider safe skeleton**

Create `src/collectors/weibo_provider.py`:

```python
from datetime import datetime

from src.details.detail_types import FetchStatus, PlatformDetail, PipelineHotRecord


class WeiboProvider:
    def __init__(self, session_ready: bool):
        self.session_ready = session_ready

    def collect_details(self, records: list[PipelineHotRecord]) -> list[PlatformDetail]:
        details: list[PlatformDetail] = []
        for index, record in enumerate(records, start=1):
            if not self.session_ready:
                details.append(
                    PlatformDetail(
                        detail_id=f"weibo_detail_{index:04d}",
                        related_hot_record_ids=[record.id],
                        platform="weibo",
                        source_method="browser_session",
                        query=record.title,
                        url=record.url,
                        title=record.title,
                        content="",
                        author="",
                        published_at="",
                        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        fetch_status=FetchStatus.FAILED,
                        error_type="login_required",
                        confidence="low",
                    )
                )
                continue
            details.append(
                PlatformDetail(
                    detail_id=f"weibo_detail_{index:04d}",
                    related_hot_record_ids=[record.id],
                    platform="weibo",
                    source_method="browser_session",
                    query=record.title,
                    url=record.url,
                    title=record.title,
                    content=f"微博登录态存在，第一版安全骨架记录待采集查询：{record.title}",
                    author="",
                    published_at="",
                    fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    fetch_status=FetchStatus.OK,
                    confidence="low",
                )
            )
        return details
```

- [ ] **Step 4: Implement Baidu provider safe skeleton**

Create `src/collectors/baidu_provider.py`:

```python
from datetime import datetime
from typing import Callable

from src.details.detail_types import FetchStatus, PlatformDetail, PipelineHotRecord


def default_searcher(query: str) -> list[dict[str, str]]:
    return []


class BaiduProvider:
    def __init__(self, searcher: Callable[[str], list[dict[str, str]]] = default_searcher):
        self.searcher = searcher

    def collect_details(self, records: list[PipelineHotRecord]) -> list[PlatformDetail]:
        details: list[PlatformDetail] = []
        for index, record in enumerate(records, start=1):
            results = self.searcher(record.title)
            first = results[0] if results else {"title": record.title, "url": record.url, "snippet": ""}
            status = FetchStatus.OK if results else FetchStatus.FAILED
            details.append(
                PlatformDetail(
                    detail_id=f"baidu_detail_{index:04d}",
                    related_hot_record_ids=[record.id],
                    platform="baidu",
                    source_method="search_api",
                    query=record.title,
                    url=first.get("url", ""),
                    title=first.get("title", record.title),
                    content=first.get("snippet", ""),
                    author="",
                    published_at="",
                    result_urls=[item.get("url", "") for item in results if item.get("url")],
                    fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    fetch_status=status,
                    error_type=None if results else "empty_content",
                    confidence="medium" if results else "low",
                )
            )
        return details
```

- [ ] **Step 5: Implement Xiaohongshu provider safe skeleton**

Create `src/collectors/xiaohongshu_provider.py`:

```python
from datetime import datetime

from src.details.detail_types import FetchStatus, PlatformDetail, PipelineHotRecord


class XiaohongshuProvider:
    def __init__(self, session_ready: bool):
        self.session_ready = session_ready

    def collect_details(self, records: list[PipelineHotRecord]) -> list[PlatformDetail]:
        details: list[PlatformDetail] = []
        for index, record in enumerate(records, start=1):
            if not self.session_ready:
                details.append(
                    PlatformDetail(
                        detail_id=f"xiaohongshu_detail_{index:04d}",
                        related_hot_record_ids=[record.id],
                        platform="xiaohongshu",
                        source_method="browser_session",
                        query=record.title,
                        url="",
                        title=record.title,
                        content="",
                        author="",
                        published_at="",
                        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        fetch_status=FetchStatus.FAILED,
                        error_type="login_required",
                        confidence="low",
                    )
                )
                continue
            details.append(
                PlatformDetail(
                    detail_id=f"xiaohongshu_detail_{index:04d}",
                    related_hot_record_ids=[record.id],
                    platform="xiaohongshu",
                    source_method="browser_session",
                    query=record.title,
                    url="",
                    title=record.title,
                    content=f"小红书登录态存在，第一版安全骨架记录待采集查询：{record.title}",
                    author="",
                    published_at="",
                    fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    fetch_status=FetchStatus.OK,
                    confidence="low",
                )
            )
        return details
```

- [ ] **Step 6: Run provider tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_platform_providers -v
```

Expected: PASS with 3 tests.

- [ ] **Step 7: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/collectors/weibo_provider.py src/collectors/baidu_provider.py src/collectors/xiaohongshu_provider.py tests/test_platform_providers.py
git commit -m "feat: add platform detail providers"
```

Expected: commit succeeds.

---

### Task 6: Topic Clustering

**Files:**
- Create: `src/clustering/__init__.py`
- Create: `src/clustering/topic_clusterer.py`
- Create: `tests/test_topic_clusterer.py`

- [ ] **Step 1: Create clustering package**

Run:

```bash
mkdir -p src/clustering
touch src/clustering/__init__.py
```

Expected: `src/clustering/__init__.py` exists.

- [ ] **Step 2: Write failing clustering tests**

Create `tests/test_topic_clusterer.py`:

```python
import unittest

from src.clustering.topic_clusterer import cluster_topics, normalize_topic_key
from src.details.detail_types import FetchStatus, PlatformDetail, PipelineHotRecord


def hot(record_id, platform, title):
    return PipelineHotRecord(
        id=record_id,
        source="dailyhotapi",
        platform=platform,
        category="domestic_social",
        title=title,
        rank=1,
        hot_value="1000",
        url="https://example.com",
        captured_at="2026-06-13 20:00:00",
    )


def detail(detail_id, hot_id, platform, query, content):
    return PlatformDetail(
        detail_id=detail_id,
        related_hot_record_ids=[hot_id],
        platform=platform,
        source_method="browser_session",
        query=query,
        url="https://example.com",
        title=query,
        content=content,
        author="",
        published_at="",
        fetched_at="2026-06-13 20:10:00",
        fetch_status=FetchStatus.OK,
        confidence="medium",
    )


class TopicClustererTests(unittest.TestCase):
    def test_normalize_topic_key_removes_spaces_and_punctuation(self):
        self.assertEqual(normalize_topic_key(" AI 新品，发布！ "), "ai新品发布")

    def test_cluster_topics_merges_records_with_same_normalized_title(self):
        records = [
            hot("hot_001", "weibo", "AI 新品发布"),
            hot("hot_002", "baidu", "AI新品发布"),
        ]
        details = [
            detail("detail_001", "hot_001", "weibo", "AI 新品发布", "微博详情"),
            detail("detail_002", "hot_002", "baidu", "AI新品发布", "百度详情"),
        ]

        clusters = cluster_topics(records, details)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].topic_id, "topic_0001")
        self.assertEqual(clusters[0].platforms, ["weibo", "baidu"])
        self.assertEqual(clusters[0].hot_record_ids, ["hot_001", "hot_002"])
        self.assertEqual(clusters[0].detail_ids, ["detail_001", "detail_002"])
        self.assertEqual(clusters[0].cluster_confidence, "high")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run clustering tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_topic_clusterer -v
```

Expected: FAIL with missing module.

- [ ] **Step 4: Implement rule-based clusterer**

Create `src/clustering/topic_clusterer.py`:

```python
import re
from collections import defaultdict

from src.details.detail_types import PlatformDetail, PipelineHotRecord, TopicCluster


def normalize_topic_key(title: str) -> str:
    lowered = title.strip().lower()
    return re.sub(r"[\s，。！？、,.!?：:；;（）()【】\[\]\"'“”‘’]", "", lowered)


def cluster_topics(records: list[PipelineHotRecord], details: list[PlatformDetail]) -> list[TopicCluster]:
    records_by_key: dict[str, list[PipelineHotRecord]] = defaultdict(list)
    for record in records:
        records_by_key[normalize_topic_key(record.title)].append(record)

    details_by_hot_id: dict[str, list[PlatformDetail]] = defaultdict(list)
    for detail in details:
        for hot_id in detail.related_hot_record_ids:
            details_by_hot_id[hot_id].append(detail)

    clusters: list[TopicCluster] = []
    for index, records_for_key in enumerate(records_by_key.values(), start=1):
        detail_ids: list[str] = []
        platforms: list[str] = []
        aliases: list[str] = []
        hot_record_ids: list[str] = []
        for record in records_for_key:
            hot_record_ids.append(record.id)
            aliases.append(record.title)
            if record.platform not in platforms:
                platforms.append(record.platform)
            for detail in details_by_hot_id.get(record.id, []):
                if detail.detail_id not in detail_ids:
                    detail_ids.append(detail.detail_id)
                if detail.platform not in platforms:
                    platforms.append(detail.platform)

        confidence = "high" if len(platforms) >= 2 and detail_ids else "medium" if detail_ids else "low"
        clusters.append(
            TopicCluster(
                topic_id=f"topic_{index:04d}",
                canonical_title=records_for_key[0].title,
                aliases=aliases,
                platforms=platforms,
                hot_record_ids=hot_record_ids,
                detail_ids=detail_ids,
                merge_reason="规则预聚类：标题归一化后相同，并关联到相同候选话题详情。",
                cluster_confidence=confidence,
            )
        )
    return clusters
```

- [ ] **Step 5: Run clustering tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_topic_clusterer -v
```

Expected: PASS with 2 tests.

- [ ] **Step 6: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/clustering/__init__.py src/clustering/topic_clusterer.py tests/test_topic_clusterer.py
git commit -m "feat: cluster related hot topics"
```

Expected: commit succeeds.

---

### Task 7: Topic Brief Generation

**Files:**
- Create: `src/summarization/__init__.py`
- Create: `src/summarization/topic_brief_generator.py`
- Create: `tests/test_topic_brief_generator.py`

- [ ] **Step 1: Create summarization package**

Run:

```bash
mkdir -p src/summarization
touch src/summarization/__init__.py
```

Expected: `src/summarization/__init__.py` exists.

- [ ] **Step 2: Write failing brief generator tests**

Create `tests/test_topic_brief_generator.py`:

```python
import unittest

from src.details.detail_types import FetchStatus, PlatformDetail, TopicCluster
from src.summarization.topic_brief_generator import generate_topic_briefs


def detail(detail_id, platform, content):
    return PlatformDetail(
        detail_id=detail_id,
        related_hot_record_ids=["hot_001"],
        platform=platform,
        source_method="browser_session",
        query="测试事件",
        url="https://example.com",
        title="测试事件",
        content=content,
        author="",
        published_at="",
        fetched_at="2026-06-13 20:10:00",
        fetch_status=FetchStatus.OK,
        confidence="medium",
    )


class TopicBriefGeneratorTests(unittest.TestCase):
    def test_generate_topic_briefs_uses_detail_content_and_platforms(self):
        cluster = TopicCluster(
            topic_id="topic_0001",
            canonical_title="测试事件",
            aliases=["测试热点"],
            platforms=["weibo", "baidu"],
            hot_record_ids=["hot_001"],
            detail_ids=["detail_001", "detail_002"],
            merge_reason="同一事件",
            cluster_confidence="high",
        )
        details = [
            detail("detail_001", "weibo", "微博讨论争议点。"),
            detail("detail_002", "baidu", "百度搜索事件背景。"),
        ]

        briefs = generate_topic_briefs([cluster], details)

        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0].topic_id, "topic_0001")
        self.assertIn("测试事件", briefs[0].summary)
        self.assertEqual(briefs[0].platform_discussion["weibo"], "微博讨论争议点。")
        self.assertEqual(briefs[0].platform_discussion["baidu"], "百度搜索事件背景。")
        self.assertEqual(briefs[0].confidence, "high")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run brief tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_topic_brief_generator -v
```

Expected: FAIL with missing module.

- [ ] **Step 4: Implement deterministic brief generator**

Create `src/summarization/topic_brief_generator.py`:

```python
from src.details.detail_types import PlatformDetail, TopicBrief, TopicCluster


def generate_topic_briefs(clusters: list[TopicCluster], details: list[PlatformDetail]) -> list[TopicBrief]:
    details_by_id = {detail.detail_id: detail for detail in details}
    briefs: list[TopicBrief] = []
    for cluster in clusters:
        cluster_details = [details_by_id[detail_id] for detail_id in cluster.detail_ids if detail_id in details_by_id]
        platform_discussion: dict[str, str] = {}
        source_evidence: list[dict[str, str]] = []
        key_facts: list[str] = []
        for detail in cluster_details:
            if detail.content and detail.platform not in platform_discussion:
                platform_discussion[detail.platform] = detail.content[:200]
            if detail.content:
                key_facts.append(detail.content[:120])
                source_evidence.append(
                    {
                        "detail_id": detail.detail_id,
                        "platform": detail.platform,
                        "evidence": detail.content[:160],
                        "confidence": detail.confidence,
                    }
                )

        confidence = cluster.cluster_confidence if source_evidence else "low"
        briefs.append(
            TopicBrief(
                topic_id=cluster.topic_id,
                canonical_title=cluster.canonical_title,
                summary=f"{cluster.canonical_title} 已归并 {len(cluster.platforms)} 个平台的相关信息。",
                key_facts=key_facts,
                platform_discussion=platform_discussion,
                timeline=[],
                source_evidence=source_evidence,
                open_questions=["是否存在更多官方或权威来源需要补充。"] if confidence != "high" else [],
                confidence=confidence,
            )
        )
    return briefs
```

- [ ] **Step 5: Run brief tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_topic_brief_generator -v
```

Expected: PASS with 1 test.

- [ ] **Step 6: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/summarization/__init__.py src/summarization/topic_brief_generator.py tests/test_topic_brief_generator.py
git commit -m "feat: generate topic briefs from details"
```

Expected: commit succeeds.

---

### Task 8: Markdown Daily Digest Renderer

**Files:**
- Create: `src/reports/__init__.py`
- Create: `src/reports/daily_digest_renderer.py`
- Create: `tests/test_daily_digest_renderer.py`

- [ ] **Step 1: Create reports package**

Run:

```bash
mkdir -p src/reports
touch src/reports/__init__.py
```

Expected: `src/reports/__init__.py` exists.

- [ ] **Step 2: Write failing renderer tests**

Create `tests/test_daily_digest_renderer.py`:

```python
import unittest

from src.details.detail_types import TopicBrief, TopicCluster
from src.reports.daily_digest_renderer import render_daily_topic_digest


class DailyDigestRendererTests(unittest.TestCase):
    def test_render_daily_topic_digest_contains_overview_and_sources(self):
        cluster = TopicCluster(
            topic_id="topic_0001",
            canonical_title="测试事件",
            aliases=["测试热点"],
            platforms=["weibo", "baidu"],
            hot_record_ids=["hot_001"],
            detail_ids=["detail_001"],
            merge_reason="同一事件",
            cluster_confidence="high",
        )
        brief = TopicBrief(
            topic_id="topic_0001",
            canonical_title="测试事件",
            summary="测试事件摘要。",
            key_facts=["事实一"],
            platform_discussion={"weibo": "微博讨论", "baidu": "百度讨论"},
            timeline=[],
            source_evidence=[
                {
                    "detail_id": "detail_001",
                    "platform": "weibo",
                    "evidence": "证据片段",
                    "confidence": "medium",
                }
            ],
            open_questions=["待确认问题"],
            confidence="medium",
        )

        markdown = render_daily_topic_digest([cluster], [brief])

        self.assertIn("# 每日热点内容汇总", markdown)
        self.assertIn("## 今日概览", markdown)
        self.assertIn("## 1. 测试事件", markdown)
        self.assertIn("### 详情证据", markdown)
        self.assertIn("detail_001", markdown)
        self.assertIn("综合置信度", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run renderer tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_daily_digest_renderer -v
```

Expected: FAIL with missing module.

- [ ] **Step 4: Implement renderer**

Create `src/reports/daily_digest_renderer.py`:

```python
from src.details.detail_types import TopicBrief, TopicCluster


def render_daily_topic_digest(clusters: list[TopicCluster], briefs: list[TopicBrief]) -> str:
    briefs_by_topic_id = {brief.topic_id: brief for brief in briefs}
    high_confidence_count = sum(1 for brief in briefs if brief.confidence == "high")
    lines = [
        "# 每日热点内容汇总",
        "",
        "## 今日概览",
        f"- 聚合主题数量：{len(clusters)}",
        f"- 高置信度主题数量：{high_confidence_count}",
        f"- 采集详情数量：{sum(len(cluster.detail_ids) for cluster in clusters)}",
        "",
    ]
    for index, cluster in enumerate(clusters, start=1):
        brief = briefs_by_topic_id.get(cluster.topic_id)
        lines.extend(
            [
                f"## {index}. {cluster.canonical_title}",
                "",
                "### 摘要",
                brief.summary if brief else "暂无整理结果。",
                "",
                "### 合并来源",
                "| 平台 | 原始标题 |",
                "|---|---|",
            ]
        )
        for platform, alias in zip(cluster.platforms, cluster.aliases):
            lines.append(f"| {platform} | {alias} |")
        lines.extend(["", "### 关键事实"])
        if brief and brief.key_facts:
            for fact in brief.key_facts:
                lines.append(f"- {fact}")
        else:
            lines.append("- 暂无可确认事实。")
        lines.extend(["", "### 平台讨论差异", "| 平台 | 讨论重点 |", "|---|---|"])
        if brief and brief.platform_discussion:
            for platform, discussion in brief.platform_discussion.items():
                lines.append(f"| {platform} | {discussion} |")
        else:
            lines.append("| - | 暂无平台讨论详情。 |")
        lines.extend(["", "### 详情证据", "| detail_id | 平台 | 置信度 | 证据 |", "|---|---|---|---|"])
        if brief and brief.source_evidence:
            for evidence in brief.source_evidence:
                lines.append(
                    f"| {evidence.get('detail_id', '')} | {evidence.get('platform', '')} | "
                    f"{evidence.get('confidence', '')} | {evidence.get('evidence', '')} |"
                )
        else:
            lines.append("| - | - | low | 暂无详情证据。 |")
        lines.extend(["", "### 待确认问题"])
        if brief and brief.open_questions:
            for question in brief.open_questions:
                lines.append(f"- {question}")
        else:
            lines.append("- 暂无。")
        confidence = brief.confidence if brief else "low"
        lines.extend(["", "### 综合置信度", confidence, ""])
    return "\n".join(lines)
```

- [ ] **Step 5: Run renderer tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_daily_digest_renderer -v
```

Expected: PASS with 1 test.

- [ ] **Step 6: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/reports/__init__.py src/reports/daily_digest_renderer.py tests/test_daily_digest_renderer.py
git commit -m "feat: render daily topic digest"
```

Expected: commit succeeds.

---

### Task 9: Pipeline Orchestrator And Make Commands

**Files:**
- Create: `src/run_pipeline.py`
- Create: `tests/test_run_pipeline.py`
- Modify: `Makefile`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing pipeline tests**

Create `tests/test_run_pipeline.py`:

```python
import tempfile
import unittest
from pathlib import Path

from src.run_pipeline import run_pipeline


class RunPipelineTests(unittest.TestCase):
    def test_run_pipeline_writes_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = run_pipeline(
                data_root=root / "data",
                reports_root=root / "reports",
                require_browser_sessions=False,
            )

            self.assertTrue((root / "data" / "raw" / "hot_records.json").exists())
            self.assertTrue((root / "data" / "details" / "platform_details.json").exists())
            self.assertTrue((root / "data" / "processed" / "topic_clusters.json").exists())
            self.assertTrue((root / "data" / "processed" / "topic_briefs.json").exists())
            self.assertTrue((root / "reports" / "daily_topic_digest.md").exists())
            self.assertIn("hot_records", result)
            self.assertIn("platform_details", result)
            self.assertIn("topic_clusters", result)
            self.assertIn("topic_briefs", result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run pipeline tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_run_pipeline -v
```

Expected: FAIL with missing `src.run_pipeline`.

- [ ] **Step 3: Implement pipeline orchestrator**

Create `src/run_pipeline.py`:

```python
from pathlib import Path

from src.collectors.baidu_provider import BaiduProvider
from src.collectors.daily_hot_collector import normalize_daily_hot_records
from src.collectors.weibo_provider import WeiboProvider
from src.collectors.xiaohongshu_provider import XiaohongshuProvider
from src.clustering.topic_clusterer import cluster_topics
from src.details.detail_store import ensure_pipeline_dirs, write_json_list
from src.hot_topic_types import HotRecord
from src.pipeline_config import (
    DAILY_TOPIC_DIGEST_PATH,
    HOT_RECORDS_PATH,
    PLATFORM_DETAILS_PATH,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    TOPIC_BRIEFS_PATH,
    TOPIC_CLUSTERS_PATH,
)
from src.reports.daily_digest_renderer import render_daily_topic_digest
from src.summarization.topic_brief_generator import generate_topic_briefs


def sample_hot_records() -> list[HotRecord]:
    return [
        HotRecord(
            platform="weibo",
            rank=1,
            title="测试热点",
            hot="1000",
            url="https://example.com/weibo",
            crawl_time="2026-06-13 20:00:00",
        ),
        HotRecord(
            platform="baidu",
            rank=2,
            title="测试热点",
            hot="800",
            url="https://example.com/baidu",
            crawl_time="2026-06-13 20:00:00",
        ),
    ]


def run_pipeline(
    data_root: Path | None = None,
    reports_root: Path | None = None,
    require_browser_sessions: bool = True,
) -> dict[str, int]:
    if data_root is None:
        data_root = HOT_RECORDS_PATH.parents[1]
    if reports_root is None:
        reports_root = REPORTS_DIR

    ensure_pipeline_dirs(data_root)
    reports_root.mkdir(parents=True, exist_ok=True)

    hot_records = normalize_daily_hot_records(sample_hot_records())
    session_ready = not require_browser_sessions
    details = []
    details.extend(WeiboProvider(session_ready=session_ready).collect_details(hot_records[:1]))
    details.extend(BaiduProvider(searcher=lambda query: [{"title": query, "url": "https://example.com/news", "snippet": "百度搜索摘要"}]).collect_details(hot_records))
    details.extend(XiaohongshuProvider(session_ready=session_ready).collect_details(hot_records[:1]))

    clusters = cluster_topics(hot_records, details)
    briefs = generate_topic_briefs(clusters, details)
    markdown = render_daily_topic_digest(clusters, briefs)

    hot_path = data_root / "raw" / "hot_records.json"
    details_path = data_root / "details" / "platform_details.json"
    clusters_path = data_root / "processed" / "topic_clusters.json"
    briefs_path = data_root / "processed" / "topic_briefs.json"
    digest_path = reports_root / "daily_topic_digest.md"

    write_json_list(hot_path, [record.to_dict() for record in hot_records])
    write_json_list(details_path, [detail.to_dict() for detail in details])
    write_json_list(clusters_path, [cluster.to_dict() for cluster in clusters])
    write_json_list(briefs_path, [brief.to_dict() for brief in briefs])
    digest_path.write_text(markdown, encoding="utf-8")

    return {
        "hot_records": len(hot_records),
        "platform_details": len(details),
        "topic_clusters": len(clusters),
        "topic_briefs": len(briefs),
    }


def main() -> None:
    result = run_pipeline()
    print(f"Hot records: {result['hot_records']}")
    print(f"Platform details: {result['platform_details']}")
    print(f"Topic clusters: {result['topic_clusters']}")
    print(f"Topic briefs: {result['topic_briefs']}")
    print(f"Digest: {DAILY_TOPIC_DIGEST_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Update Makefile commands**

Modify `Makefile` so it contains these targets while preserving existing `PYTHON ?= python3`:

```makefile
PYTHON ?= python3

.PHONY: demo test check-sessions login-weibo login-xiaohongshu collect-hot collect-details cluster-topics generate-digest run-pipeline

demo:
	$(PYTHON) -m src.demo_collect_hot_topics

test:
	$(PYTHON) -m unittest discover -s tests -v

check-sessions:
	$(PYTHON) - <<'PY'
from src.browser.session_manager import check_required_sessions
from src.pipeline_config import WEIBO_STATE_PATH, XIAOHONGSHU_STATE_PATH
statuses = check_required_sessions({"weibo": WEIBO_STATE_PATH, "xiaohongshu": XIAOHONGSHU_STATE_PATH})
for status in statuses.values():
    print(f"{status.platform}: {status.status} - {status.message}")
PY

login-weibo:
	@echo "请手动登录微博并将 Playwright storage_state 保存到 data/browser_state/weibo.json，然后运行 make check-sessions。"

login-xiaohongshu:
	@echo "请手动登录小红书并将 Playwright storage_state 保存到 data/browser_state/xiaohongshu.json，然后运行 make check-sessions。"

collect-hot:
	$(PYTHON) -m src.run_pipeline

collect-details:
	$(PYTHON) -m src.run_pipeline

cluster-topics:
	$(PYTHON) -m src.run_pipeline

generate-digest:
	$(PYTHON) -m src.run_pipeline

run-pipeline:
	$(PYTHON) -m src.run_pipeline
```

- [ ] **Step 5: Update gitignore for local artifacts**

Append these lines to `.gitignore`:

```gitignore
data/browser_state/
data/snapshots/
data/screenshots/
data/raw/hot_records.json
data/details/platform_details.json
data/processed/topic_clusters.json
data/processed/topic_briefs.json
reports/daily_topic_digest.md
```

- [ ] **Step 6: Run pipeline tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_run_pipeline -v
```

Expected: PASS with 1 test.

- [ ] **Step 7: Run full tests**

Run:

```bash
make test
```

Expected: all tests pass.

- [ ] **Step 8: Run pipeline command**

Run:

```bash
make run-pipeline
```

Expected output includes:

```text
Hot records:
Platform details:
Topic clusters:
Topic briefs:
Digest:
```

- [ ] **Step 9: Verify generated report exists**

Run:

```bash
test -f reports/daily_topic_digest.md && sed -n '1,80p' reports/daily_topic_digest.md
```

Expected: output starts with `# 每日热点内容汇总`.

- [ ] **Step 10: Commit**

Run:

```bash
git add src/run_pipeline.py tests/test_run_pipeline.py Makefile .gitignore
git commit -m "feat: add manual hot topic pipeline"
```

Expected: commit succeeds.

---

## Self-Review Checklist

- Spec coverage:
  - DailyHotApi multi-platform hot records: Task 3.
  - Details stored separately: Tasks 1, 2, 5, 9.
  - Login/session checks before Weibo and Xiaohongshu collection: Task 4 and Task 9.
  - Failure statuses for login/captcha/rate limit: Task 4 and Task 5.
  - LLM-ready same-topic clustering: Task 6.
  - LLM-ready hot topic brief generation: Task 7.
  - JSON and Markdown outputs: Tasks 2, 8, 9.
  - Manual first-version commands: Task 9.
- Placeholder scan:
  - The plan intentionally uses deterministic first-version provider skeletons for browser platforms. Real page selectors are not included because they must be verified during manual logged-in browser sessions and will be planned after the safe pipeline exists.
- Type consistency:
  - `PipelineHotRecord`, `PlatformDetail`, `TopicCluster`, and `TopicBrief` are defined in Task 1 and reused consistently in later tasks.
