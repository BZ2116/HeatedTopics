# Detail Cache and Session Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Limit expensive detail collection to Weibo, Baidu, Xiaohongshu, Bilibili, and Juejin while adding 7-day route/detail caching and conservative login/session safety behavior.

**Architecture:** Keep DailyHot as the broad topic discovery layer, then filter expensive detail providers through a small configured platform allowlist. Add a file-based cache store under `data/cache/` with TTL checks, and keep Weibo/Xiaohongshu browser behavior low-frequency, session-aware, and stop-on-guard.

**Tech Stack:** Python standard library, existing `unittest`/`pytest`, Playwright for browser-based detail collection, JSON files for cache and pipeline artifacts.

---

## File Structure

- Modify `src/core_pipeline/source_registry.py`: add detail platform configuration, per-platform limits, and helper functions.
- Create `src/core_pipeline/cache_store.py`: file-based cache key hashing, TTL validation, JSON read/write helpers.
- Modify `src/core_pipeline/dailyhot_client.py`: optional cache-aware DailyHot route collection.
- Modify `src/core_pipeline/detail_collector.py`: filter expensive detail collection to enabled platforms and use cache around provider calls.
- Modify `src/core_pipeline/browser_detail_fetcher.py`: add conservative per-page delay/jitter knobs and stop-on-guard behavior.
- Modify `src/core_pipeline/run.py`: add `--refresh`, `--detail-platforms`, cache injection, and progress messages for skipped login platforms.
- Modify `src/core_pipeline/report_renderer.py`: keep non-detail platforms in report as DailyHot metadata instead of treating them as missing detail.
- Create/modify tests under `tests/core_pipeline/`: source registry, cache store, DailyHot cache, detail filtering/cache, partial login, CLI behavior.

---

### Task 1: Add Detail Platform Configuration

**Files:**
- Modify: `src/core_pipeline/source_registry.py`
- Test: `tests/core_pipeline/test_source_registry.py`

- [ ] **Step 1: Write failing tests for detail platform config**

Add these tests to `tests/core_pipeline/test_source_registry.py`:

```python
from src.core_pipeline.source_registry import (
    DETAIL_ENABLED_PLATFORMS,
    DETAIL_PLATFORM_LIMITS,
    platform_detail_enabled,
)


def test_detail_enabled_platforms_are_limited_to_expensive_sources():
    assert DETAIL_ENABLED_PLATFORMS == ("weibo", "baidu", "xiaohongshu", "bilibili", "juejin")


def test_platform_detail_enabled_uses_allowlist():
    assert platform_detail_enabled("weibo") is True
    assert platform_detail_enabled("baidu") is True
    assert platform_detail_enabled("xiaohongshu") is True
    assert platform_detail_enabled("bilibili") is True
    assert platform_detail_enabled("juejin") is True
    assert platform_detail_enabled("zhihu") is False
    assert platform_detail_enabled("github") is False


def test_detail_platform_limits_are_conservative():
    assert DETAIL_PLATFORM_LIMITS["weibo"] <= 20
    assert DETAIL_PLATFORM_LIMITS["xiaohongshu"] <= 20
    assert DETAIL_PLATFORM_LIMITS["baidu"] <= 80
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_source_registry.py -q
```

Expected: FAIL because `DETAIL_ENABLED_PLATFORMS`, `DETAIL_PLATFORM_LIMITS`, and `platform_detail_enabled` do not exist.

- [ ] **Step 3: Implement config**

Add to `src/core_pipeline/source_registry.py`:

```python
DETAIL_ENABLED_PLATFORMS = ("weibo", "baidu", "xiaohongshu", "bilibili", "juejin")

DETAIL_PLATFORM_LIMITS = {
    "weibo": 20,
    "xiaohongshu": 20,
    "baidu": 80,
    "bilibili": 80,
    "juejin": 30,
}


def platform_detail_enabled(platform: str, enabled_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS) -> bool:
    return platform in enabled_platforms
```

- [ ] **Step 4: Verify tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_source_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/source_registry.py tests/core_pipeline/test_source_registry.py
git commit -m "feat: configure detail-enabled platforms"
```

---

### Task 2: Add File-Based 7-Day Cache Store

**Files:**
- Create: `src/core_pipeline/cache_store.py`
- Test: `tests/core_pipeline/test_cache_store.py`

- [ ] **Step 1: Write failing cache tests**

Create `tests/core_pipeline/test_cache_store.py`:

```python
from datetime import datetime, timedelta, timezone

from src.core_pipeline.cache_store import CacheStore


def test_cache_store_reads_fresh_entry(tmp_path):
    store = CacheStore(tmp_path, ttl_days=7, now=lambda: datetime(2026, 6, 23, tzinfo=timezone.utc))
    store.write("detail:baidu:test", {"value": 1}, fetched_at="2026-06-20T00:00:00+00:00")

    assert store.read("detail:baidu:test") == {"value": 1}


def test_cache_store_ignores_expired_entry(tmp_path):
    store = CacheStore(tmp_path, ttl_days=7, now=lambda: datetime(2026, 6, 23, tzinfo=timezone.utc))
    store.write("detail:baidu:test", {"value": 1}, fetched_at="2026-06-01T00:00:00+00:00")

    assert store.read("detail:baidu:test") is None


def test_cache_store_bypasses_reads_when_refresh_is_true(tmp_path):
    store = CacheStore(tmp_path, ttl_days=7, refresh=True, now=lambda: datetime(2026, 6, 23, tzinfo=timezone.utc))
    store.write("dailyhot:weibo:today:2026-06-23", {"rows": []}, fetched_at="2026-06-23T00:00:00+00:00")

    assert store.read("dailyhot:weibo:today:2026-06-23") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_cache_store.py -q
```

Expected: FAIL because `src.core_pipeline.cache_store` does not exist.

- [ ] **Step 3: Implement cache store**

Create `src/core_pipeline/cache_store.py`:

```python
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


class CacheStore:
    def __init__(
        self,
        root: str | Path = "data/cache",
        ttl_days: int = 7,
        refresh: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.ttl = timedelta(days=ttl_days)
        self.refresh = refresh
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self, key: str) -> Any | None:
        if self.refresh:
            return None
        path = self._path_for_key(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        fetched_at = _parse_datetime(str(payload.get("fetched_at", "")))
        if fetched_at is None:
            return None
        if self.now() - fetched_at > self.ttl:
            return None
        return payload.get("data")

    def write(self, key: str, data: Any, fetched_at: str | None = None) -> None:
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "key": key,
            "fetched_at": fetched_at or self.now().isoformat(timespec="seconds"),
            "data": data,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        namespace = key.split(":", 1)[0] if ":" in key else "misc"
        return self.root / namespace / f"{digest}.json"


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
```

- [ ] **Step 4: Verify cache tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_cache_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/cache_store.py tests/core_pipeline/test_cache_store.py
git commit -m "feat: add file cache store"
```

---

### Task 3: Cache DailyHot Route Collection

**Files:**
- Modify: `src/core_pipeline/dailyhot_client.py`
- Test: `tests/core_pipeline/test_dailyhot_client.py`

- [ ] **Step 1: Write failing DailyHot cache test**

Add to `tests/core_pipeline/test_dailyhot_client.py`:

```python
from src.core_pipeline.cache_store import CacheStore


def test_collect_dailyhot_records_reuses_route_cache(tmp_path):
    cache = CacheStore(tmp_path, now=lambda: __import__("datetime").datetime(2026, 6, 23, tzinfo=__import__("datetime").timezone.utc))
    cache.write(
        "dailyhot:weibo:today",
        [{"data": {"title": "cached weibo topic", "hot": "100"}}],
        fetched_at="2026-06-23T00:00:00+00:00",
    )
    calls = []

    records = collect_dailyhot_records(
        routes=("weibo",),
        captured_at="2026-06-23T08:00:00+08:00",
        fetcher=lambda route: calls.append(route) or {"data": [{"title": "fresh topic"}]},
        cache_store=cache,
        cache_window="today",
    )

    assert calls == []
    assert records[0].title == "cached weibo topic"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_dailyhot_client.py -q
```

Expected: FAIL because `collect_dailyhot_records` does not accept `cache_store` or `cache_window`.

- [ ] **Step 3: Implement DailyHot cache parameters**

Modify `collect_dailyhot_records` signature in `src/core_pipeline/dailyhot_client.py`:

```python
def collect_dailyhot_records(
    routes: tuple[str, ...],
    captured_at: str,
    fetcher: Callable[[str], dict[str, Any]],
    baidu_html_fetcher: Callable[[], str] = fetch_baidu_top_html,
    cache_store=None,
    cache_window: str = "today",
) -> list[HotRecord]:
```

Inside the loop, before `payload = fetcher(route)`:

```python
cache_key = f"dailyhot:{route}:{cache_window}"
cached_rows = cache_store.read(cache_key) if cache_store is not None else None
if cached_rows is not None:
    payload = {"data": [row.get("data", row) for row in cached_rows]}
else:
    payload = fetcher(route)
    if cache_store is not None:
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        cache_store.write(cache_key, [{"data": row} for row in rows], fetched_at=captured_at)
```

Keep existing Baidu fallback behavior after payload normalization.

- [ ] **Step 4: Verify DailyHot tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_dailyhot_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/dailyhot_client.py tests/core_pipeline/test_dailyhot_client.py
git commit -m "feat: cache dailyhot route responses"
```

---

### Task 4: Filter Expensive Detail Collection to Enabled Platforms

**Files:**
- Modify: `src/core_pipeline/detail_collector.py`
- Test: `tests/core_pipeline/test_detail_collector.py`

- [ ] **Step 1: Write failing detail filtering tests**

Add to `tests/core_pipeline/test_detail_collector.py`:

```python
def test_collect_topic_details_skips_social_fetch_for_non_detail_platform():
    topic = {
        "topic_key": "zhihutopic",
        "canonical_title": "zhihu topic",
        "hot_record_ids": ["hot_zhihu_001"],
        "records": [hot_record("hot_zhihu_001", "zhihu", "zhihu topic")],
    }

    def social_detail_fetcher(platform: str, query: str):
        raise AssertionError("non-detail platforms must not trigger social detail fetch")

    evidence = collect_topic_details(
        topics=[topic],
        fetched_at="2026-06-22T20:10:00+08:00",
        search_provider=lambda query: [],
        session_status={"weibo": "ok", "xiaohongshu": "ok"},
        social_detail_fetcher=social_detail_fetcher,
        enabled_detail_platforms=("baidu", "weibo", "xiaohongshu", "bilibili", "juejin"),
    )

    assert any(row.platform == "zhihu" and row.source_method == "dailyhot_metadata" for row in evidence)
    assert not any(row.platform == "weibo" for row in evidence)
    assert not any(row.platform == "xiaohongshu" for row in evidence)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_detail_collector.py -q
```

Expected: FAIL because `enabled_detail_platforms` and DailyHot metadata evidence do not exist.

- [ ] **Step 3: Add metadata evidence helper**

Add to `src/core_pipeline/detail_collector.py`:

```python
def dailyhot_metadata_evidence(
    record: HotRecord,
    fetched_at: str,
    related_hot_record_ids: list[str],
    topic_key: str | None = None,
) -> DetailEvidence:
    content = "\n".join(
        part
        for part in [
            f"Title: {record.title}",
            f"Description: {record.desc}" if record.desc else "",
            f"URL: {record.url or record.mobile_url}" if record.url or record.mobile_url else "",
        ]
        if part
    )
    return DetailEvidence(
        evidence_id=f"evidence_metadata_{record.id}",
        topic_key=topic_key or record.title,
        related_hot_record_ids=related_hot_record_ids,
        platform=record.platform,
        source_role="auxiliary",
        source_method="dailyhot_metadata",
        query=record.title,
        url=record.url or record.mobile_url,
        title=f"{record.platform} DailyHot metadata: {record.title}",
        content=content,
        author=record.author,
        published_at=record.timestamp,
        metrics={"rank": record.rank, "hot_value": record.hot_value},
        comments_preview=[],
        result_urls=[record.url or record.mobile_url] if record.url or record.mobile_url else [],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status="ok" if content else "empty_content",
        error_type=None if content else "empty_content",
        confidence="low",
        raw_payload={"record": record.to_dict()},
    )
```

- [ ] **Step 4: Add enabled platform branch**

Modify `collect_topic_details` signature:

```python
def collect_topic_details(
    topics: list[dict[str, Any]],
    fetched_at: str,
    search_provider: SearchProvider,
    session_status: dict[str, str],
    page_fetcher: PageFetcher | None = None,
    social_detail_fetcher: SocialDetailFetcher | None = None,
    enabled_detail_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS,
) -> list[DetailEvidence]:
```

Import:

```python
from src.core_pipeline.source_registry import DETAIL_ENABLED_PLATFORMS
```

At the start of each topic loop after `records` is available:

```python
topic_platforms = {record.platform for record in records}
if not topic_platforms.intersection(enabled_detail_platforms):
    for record in records:
        evidence_rows.append(dailyhot_metadata_evidence(record, fetched_at, related_ids, topic_key))
    continue
```

- [ ] **Step 5: Verify detail tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_detail_collector.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/core_pipeline/detail_collector.py tests/core_pipeline/test_detail_collector.py
git commit -m "feat: limit expensive detail collection"
```

---

### Task 5: Cache Detail Evidence

**Files:**
- Modify: `src/core_pipeline/detail_collector.py`
- Test: `tests/core_pipeline/test_detail_collector.py`

- [ ] **Step 1: Write failing detail cache test**

Add:

```python
from src.core_pipeline.cache_store import CacheStore


def test_collect_topic_details_reuses_detail_cache(tmp_path):
    cache = CacheStore(tmp_path, now=lambda: __import__("datetime").datetime(2026, 6, 23, tzinfo=__import__("datetime").timezone.utc))
    cached = {
        "evidence_id": "evidence_baidu_hot_weibo_001",
        "topic_key": "cachedtopic",
        "related_hot_record_ids": ["hot_weibo_001"],
        "platform": "baidu",
        "source_role": "required",
        "source_method": "search_results",
        "query": "cached topic",
        "url": "",
        "title": "cached title",
        "content": "cached detail body",
        "author": "",
        "published_at": "",
        "metrics": {},
        "comments_preview": [],
        "result_urls": [],
        "raw_snapshot_path": "",
        "screenshot_path": "",
        "fetched_at": "2026-06-23T00:00:00+00:00",
        "fetch_status": "ok",
        "error_type": None,
        "confidence": "medium",
        "raw_payload": {},
    }
    cache.write("detail:baidu:cachedtopic", cached, fetched_at="2026-06-23T00:00:00+00:00")
    topic = {
        "topic_key": "cachedtopic",
        "canonical_title": "cached topic",
        "hot_record_ids": ["hot_weibo_001"],
        "records": [hot_record("hot_weibo_001", "weibo", "cached topic")],
    }

    evidence = collect_topic_details(
        topics=[topic],
        fetched_at="2026-06-23T08:00:00+08:00",
        search_provider=lambda query: (_ for _ in ()).throw(AssertionError("search should not run")),
        session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        cache_store=cache,
    )

    assert any(row.platform == "baidu" and row.content == "cached detail body" for row in evidence)
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_detail_collector.py -q
```

Expected: FAIL because `cache_store` is not accepted.

- [ ] **Step 3: Implement detail cache helpers**

In `detail_collector.py`, add:

```python
def _detail_cache_key(platform: str, topic_key: str) -> str:
    return f"detail:{platform}:{topic_key}"


def _read_detail_cache(cache_store, platform: str, topic_key: str) -> DetailEvidence | None:
    if cache_store is None:
        return None
    row = cache_store.read(_detail_cache_key(platform, topic_key))
    if row is None:
        return None
    return DetailEvidence(**row)


def _write_detail_cache(cache_store, evidence: DetailEvidence) -> None:
    if cache_store is None:
        return
    cache_store.write(_detail_cache_key(evidence.platform, evidence.topic_key), evidence.to_dict(), fetched_at=evidence.fetched_at)
```

Modify `collect_topic_details` signature to include `cache_store=None`.

Before each provider call for Baidu, Weibo, Xiaohongshu, Bilibili, and metadata evidence, call `_read_detail_cache`. After creating evidence, call `_write_detail_cache`.

- [ ] **Step 4: Verify detail cache tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_detail_collector.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/detail_collector.py tests/core_pipeline/test_detail_collector.py
git commit -m "feat: cache detail evidence"
```

---

### Task 6: Add CLI Cache Controls

**Files:**
- Modify: `src/core_pipeline/run.py`
- Test: `tests/core_pipeline/test_run.py`

- [ ] **Step 1: Write failing CLI behavior tests**

Add to `tests/core_pipeline/test_run.py`:

```python
from src.core_pipeline.cache_store import CacheStore


def test_run_recent_detail_collection_passes_cache_to_dailyhot_and_details(tmp_path):
    cache = CacheStore(tmp_path)
    result = run_recent_detail_collection(
        window="today",
        root=tmp_path,
        routes=("weibo",),
        route_fetcher=lambda route: {"data": [{"title": "cache wire topic", "hot": "100"}]},
        search_provider=lambda query: [{"title": "detail", "snippet": "body", "url": "https://example.com"}],
        session_status={"weibo": "login_required", "xiaohongshu": "login_required"},
        cache_store=cache,
        now=lambda: "2026-06-23T08:00:00+08:00",
    )

    assert result["topics_count"] == 1
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_run.py -q
```

Expected: FAIL because `run_recent_detail_collection` does not accept `cache_store`.

- [ ] **Step 3: Wire cache into run function**

Import:

```python
from src.core_pipeline.cache_store import CacheStore
```

Modify `run_recent_detail_collection` signature:

```python
cache_store=None,
refresh: bool = False,
detail_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS,
```

At start:

```python
if cache_store is None:
    cache_store = CacheStore(refresh=refresh)
```

Pass to `collect_dailyhot_records`:

```python
records = collect_dailyhot_records(
    routes=routes,
    captured_at=captured_at,
    fetcher=route_fetcher,
    cache_store=cache_store,
    cache_window=window,
)
```

Pass to `collect_topic_details`:

```python
cache_store=cache_store,
enabled_detail_platforms=detail_platforms,
```

- [ ] **Step 4: Add argparse options**

In `main()` add:

```python
parser.add_argument("--refresh", action="store_true")
parser.add_argument("--detail-platforms", default="")
```

Before calling `run_recent_detail_collection`:

```python
detail_platforms = tuple(part.strip() for part in args.detail_platforms.split(",") if part.strip()) or DETAIL_ENABLED_PLATFORMS
run_recent_detail_collection(
    window=args.window,
    progress=print_progress,
    refresh=args.refresh,
    detail_platforms=detail_platforms,
)
```

- [ ] **Step 5: Verify run tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_run.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/core_pipeline/run.py tests/core_pipeline/test_run.py
git commit -m "feat: add cache controls to collection command"
```

---

### Task 7: Add Conservative Session Keepalive and Guard Handling

**Files:**
- Modify: `src/core_pipeline/session_gate.py`
- Modify: `src/core_pipeline/browser_detail_fetcher.py`
- Test: `tests/core_pipeline/test_session_gate.py`

- [ ] **Step 1: Write failing session status tests**

Add to `tests/core_pipeline/test_session_gate.py`:

```python
from src.core_pipeline.session_gate import summarize_session_status


def test_summarize_session_status_lists_missing_platforms():
    summary = summarize_session_status({"weibo": "login_required", "xiaohongshu": "ok"})

    assert summary["ok"] == ["xiaohongshu"]
    assert summary["missing"] == ["weibo"]
    assert "uv run python -m src.browser.session_manager login weibo" in summary["login_commands"]
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_session_gate.py -q
```

Expected: FAIL because `summarize_session_status` does not exist.

- [ ] **Step 3: Implement session summary**

Add to `src/core_pipeline/session_gate.py`:

```python
def summarize_session_status(status: dict[str, str]) -> dict[str, object]:
    ok = [platform for platform, value in status.items() if value == "ok"]
    missing = [platform for platform, value in status.items() if value != "ok"]
    commands = [f"uv run python -m src.browser.session_manager login {platform}" for platform in missing]
    return {
        "ok": ok,
        "missing": missing,
        "login_commands": commands,
    }
```

- [ ] **Step 4: Add delay/jitter knobs to browser fetcher**

Modify `fetch_social_details_with_browser` in `browser_detail_fetcher.py`:

```python
def fetch_social_details_with_browser(
    platform: str,
    query: str,
    browser_state_dir: str | Path = "data/browser_state",
    timeout_ms: int = 20000,
    settle_delay_ms: int = 2500,
) -> list[dict[str, object]]:
```

Replace hard-coded `page.wait_for_timeout(2500)` with:

```python
page.wait_for_timeout(settle_delay_ms)
```

Keep existing `detect_page_guard(page)` behavior and raise `RuntimeError(guard)` when a guard appears. Do not add captcha bypass, proxy rotation, fingerprint spoofing, or automated login solving.

- [ ] **Step 5: Verify session tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_session_gate.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/core_pipeline/session_gate.py src/core_pipeline/browser_detail_fetcher.py tests/core_pipeline/test_session_gate.py
git commit -m "feat: summarize session state safely"
```

---

### Task 8: Report Non-Detail Sources Clearly

**Files:**
- Modify: `src/core_pipeline/report_renderer.py`
- Test: `tests/core_pipeline/test_report_renderer.py`

- [ ] **Step 1: Write failing report test**

Add:

```python
def test_recent_report_shows_dailyhot_metadata_without_missing_detail_warning():
    record = HotRecord(
        id="hot_zhihu_001",
        source="dailyhotapi",
        platform="zhihu",
        route="zhihu",
        category="core_discovery",
        title="zhihu metadata topic",
        rank=1,
        hot_value="100",
        url="https://example.com/zhihu",
        mobile_url="",
        desc="DailyHot summary only",
        author="",
        cover="",
        timestamp="",
        captured_at="2026-06-23T08:00:00+08:00",
        raw_payload={},
        fetch_status="ok",
        error_type=None,
    )
    evidence = DetailEvidence(
        evidence_id="evidence_metadata_hot_zhihu_001",
        topic_key="zhihumetadatatopic",
        related_hot_record_ids=["hot_zhihu_001"],
        platform="zhihu",
        source_role="auxiliary",
        source_method="dailyhot_metadata",
        query="zhihu metadata topic",
        url="https://example.com/zhihu",
        title="zhihu DailyHot metadata",
        content="DailyHot summary only",
        author="",
        published_at="",
        metrics={},
        comments_preview=[],
        result_urls=["https://example.com/zhihu"],
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at="2026-06-23T08:10:00+08:00",
        fetch_status="ok",
        error_type=None,
        confidence="low",
        raw_payload={},
    )

    markdown = render_recent_hot_topics_report(
        topics=[{"topic_key": "zhihumetadatatopic", "canonical_title": "zhihu metadata topic", "hot_record_ids": ["hot_zhihu_001"], "records": [record]}],
        evidence_rows=[evidence],
        generated_at="2026-06-23T08:20:00+08:00",
        window="today",
    )

    assert "dailyhot_metadata" in markdown
    assert "Required detail alerts" not in markdown
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_report_renderer.py -q
```

Expected: FAIL if metadata evidence is not rendered clearly or still triggers required detail alerts.

- [ ] **Step 3: Adjust report renderer**

In `render_recent_hot_topics_report`, treat `source_method == "dailyhot_metadata"` as valid detail display but not required detail completeness. Render each row as:

```python
lines.append(f"- `{row.platform}` / `{row.source_method}` / {url}")
```

Only show `Required detail alerts` when the topic contains at least one detail-enabled platform. Use:

```python
detail_platforms = {"weibo", "baidu", "xiaohongshu", "bilibili", "juejin"}
topic_has_required_platform = any(record.platform in detail_platforms for record in records)
if topic_has_required_platform and required_status.missing_required_details:
    ...
```

- [ ] **Step 4: Verify report tests pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests/core_pipeline/test_report_renderer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/report_renderer.py tests/core_pipeline/test_report_renderer.py
git commit -m "feat: report metadata-only sources clearly"
```

---

### Task 9: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run full test suite**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run pytest tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run cache smoke command with injected small route set**

Run a fast local smoke through Python:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run python -c "from pathlib import Path; from src.core_pipeline.run import run_recent_detail_collection; result=run_recent_detail_collection(window='today', root=Path('tmp/cache-smoke'), routes=('weibo',), route_fetcher=lambda route:{'data':[{'title':'smoke topic','hot':'100','url':'https://example.com'}]}, search_provider=lambda query:[{'title':'detail','snippet':'body','url':'https://example.com/detail'}], session_status={'weibo':'login_required','xiaohongshu':'login_required'}); print(result)"
```

Expected: command completes, writes `tmp/cache-smoke` artifacts, and prints a result with `topics_count` equal to `1`.

- [ ] **Step 3: Run production command carefully**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run python -m src.core_pipeline.run collect-recent-details --window today
```

Expected: full DailyHot discovery runs; detail collection only targets configured detail platforms; missing Weibo/Xiaohongshu login state is reported and skipped without aborting; cache is populated.

- [ ] **Step 4: Run production command again to verify cache reuse**

Run the same command again:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'; uv run python -m src.core_pipeline.run collect-recent-details --window today
```

Expected: repeated run is faster and reads route/detail data from `data/cache`.

- [ ] **Step 5: Commit final verification updates**

If smoke artifacts were created under `tmp/`, remove them. Then:

```powershell
git status --short
git add docs/superpowers/plans/2026-06-23-detail-cache-and-session-safety.md
git commit -m "docs: add detail cache implementation plan"
```

---

## Self-Review

Spec coverage:

- Detail collection limited to Weibo, Baidu, Xiaohongshu, Bilibili, and Juejin: covered by Tasks 1, 4, and 8.
- Other DailyHot sources kept as metadata only: covered by Tasks 4 and 8.
- 7-day route cache: covered by Tasks 2 and 3.
- 7-day detail cache: covered by Tasks 2 and 5.
- `--refresh` and `--detail-platforms`: covered by Task 6.
- Partial login state continues running: covered by Tasks 6 and 7.
- Conservative session keepalive and stop-on-guard: covered by Task 7.
- Full verification: covered by Task 9.

Placeholder scan:

- No `TBD`, `TODO`, or unspecified implementation steps remain.
- Every test task includes concrete code and commands.
- Every implementation task names exact files and functions.

Type consistency:

- `CacheStore.read/write`, `collect_topic_details(... cache_store, enabled_detail_platforms)`, and `run_recent_detail_collection(... cache_store, refresh, detail_platforms)` are introduced before later tasks use them.
