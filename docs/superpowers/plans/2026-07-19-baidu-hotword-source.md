# Baidu Hot-Word Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `baidu` as a third data source following the same shape as `juejin`: a one-platform pipeline that emits `hot_items.json`, `report.md`, and `article_texts/` for a `UserProfile`, leaving cross-source aggregation for later.

**Architecture:** Three-stage fetch (board JSON → search HTML → article HTML) with single-flight daily caches for each stage. `pipeline.run_baidu_pipeline` is a thin orchestrator that delegates to `providers/baidu.py` for parsing and to `baidu_cache.py` for caching. CLI mirrors the existing `juejin` / `toutiao` surface.

**Tech Stack:** Python 3.14, pytest, urllib stdlib (matches the rest of the project — no new deps).

**Spec:** `docs/superpowers/specs/2026-07-19-baidu-hotword-source-design.md`

---

## File Structure

### Create

| Path | Responsibility |
|---|---|
| `src/heated_topics_v3/providers/baidu.py` | Three pure parsers + fetcher wrappers for board / search / article |
| `src/heated_topics_v3/providers/__init__.py` re-export | Add `baidu` to the public list (existing file — see `__init__.py` lines 1-2) |
| `src/heated_topics_v3/baidu_cache.py` | Daily + per-key single-flight cache mirrors `toutiao_search_cache.py` |
| `tests/providers/test_baidu_parsing.py` | Pure-parser tests with inline fixtures |
| `tests/test_baidu_pipeline.py` | Pipeline integration test (mirrors `tests/test_juejin_pipeline.py`) |
| `tests/test_baidu_cache.py` | Cache single-flight, schema-mismatch, lock-timeout, hit-path (mirrors `tests/test_toutiao_search_cache.py`) |
| `tests/test_baidu_offline.py` | `--offline` mode: monkeypatch urllib and assert zero calls when caches empty |
| `scripts/probe_baidu_board.py` | Single kept reference probe (documented, kept for future debugging) |
| `docs/superpowers/plans/2026-07-19-baidu-hotword-source.md` | This file (already created) |

### Modify

| Path | Change |
|---|---|
| `src/heated_topics_v3/pipeline.py` | Add `run_baidu_pipeline(...)` and re-export from `pipeline` |
| `src/heated_topics_v3/reporting.py` | Add `render_baidu_report(profile, matches, fetched_at, item_details)` |
| `src/heated_topics_v3/cli.py` | Add `baidu` subcommand + `_handle_baidu` + `_add_baidu_args` |
| `docs/specs/platform-hot-list-matrix.md` | Move `baidu` from "first batch planned" to "first batch done" with link to spec |
| `README.md` | Add "Baidu 热搜" command example under the existing juejin / toutiao sections |

### Delete

| Path | Reason |
|---|---|
| `scripts/probe_baijiahao.py` | One-shot, replaced by `probe_baidu_board.py` |
| `scripts/probe_baijiahao_m.py` | One-shot, replaced |
| `scripts/probe_baijiahao_api.py` | One-shot, replaced |
| `scripts/probe_baijiahao_api_v2.py` | One-shot, replaced |
| `scripts/probe_baijiahao_search.py` | One-shot, replaced |

### Untouched

`tmp/baijiahao_probe/` — fits the project's `tmp/` runtime-products convention (see `CLAUDE.md`); does not enter source.

---

## Task 1: Board response parser

**Files:**
- Create: `src/heated_topics_v3/providers/baidu.py`
- Create: `tests/providers/__init__.py` (empty package marker so the `tests/providers/` namespace works)
- Test: `tests/providers/test_baidu_parsing.py`

- [ ] **Step 1: Create `tests/providers/__init__.py`**

Write the empty file:

```python
"""Tests for the per-provider parsing layer."""
```

- [ ] **Step 2: Write failing test for board parser**

In `tests/providers/test_baidu_parsing.py`:

```python
from heated_topics_v3.providers.baidu import parse_baidu_board_response


BOARD_FIXTURE = """{
  "success": true,
  "data": {"cards": [{"component": "tabTextList", "title": "热搜榜", "content": [
    {"content": [
      {"isTop": true, "url": "https://m.baidu.com/s?word=%E6%90%BA%E6%89%8B&sa=fyb_news", "word": "携手"},
      {"isTop": false, "index": 1, "url": "https://m.baidu.com/s?word=%E6%B3%95&sa=fyb_news", "word": "法国", "hotTag": "3"},
      {"isTop": false, "index": 2, "url": "https://m.baidu.com/s?word=%E4%BD%BF%E9%A6%86&sa=fyb_news", "word": "使馆"}
    ]}
  ]}]}
}"""


def test_parse_board_returns_hotword_hot_items():
    items = parse_baidu_board_response(
        BOARD_FIXTURE,
        fetched_at="2026-07-19T20:00:00+08:00",
        matched_query_ids=("tech_ai_creator_q_001_core_hot",),
    )
    assert [i.item_id for i in items] == [
        "baidu_word_携手",  # uses sha1? No — see impl below; parser uses word text
        "baidu_word_法国",
        "baidu_word_使馆",
    ]
    assert all(it.platform == "baidu" for it in items)
    assert all(it.item_type == "hotword" for it in items)
    assert items[0].rank is None  # isTop row
    assert items[1].rank == 1
    assert items[1].heat.metric_name == "hot_tag"
    assert items[1].heat.value == 3
    assert items[1].matched_query_ids == ("tech_ai_creator_q_001_core_hot",)
```

Note: pick the implementation strategy for `item_id` in step 3. The fixture above encodes `word` literally to keep tests greppable.

- [ ] **Step 3: Run test to confirm it fails**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/providers/test_baidu_parsing.py::test_parse_board_returns_hotword_hot_items -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'heated_topics_v3.providers.baidu'`.

- [ ] **Step 4: Implement parser in providers/baidu.py**

Write this minimum to make the test pass (other parsers and caches come in later tasks):

```python
"""Pure parsers for Baidu board / search / article responses.

No I/O lives here — every function takes the response text and the matching
context, returns a domain object. Network access is owned by the pipeline.
"""
from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from typing import Any

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail


def _safe_word_slug(word: str) -> str:
    """Stable identifier for a hot word. Uses sha1 prefix for very long words."""
    digest = hashlib.sha1(word.encode("utf-8")).hexdigest()[:12]
    return f"{digest}_{word[:24]}"


def parse_baidu_board_response(
    response_text: str,
    fetched_at: str,
    matched_query_ids: tuple[str, ...] = (),
) -> list[HotItem]:
    payload = json.loads(response_text)
    if not payload.get("success"):
        return []
    cards = (payload.get("data") or {}).get("cards") or []
    if not cards:
        return []
    rows = ((cards[0].get("content") or [{}])[0].get("content")) or []
    items: list[HotItem] = []
    for row in rows:
        word = str(row.get("word", "")).strip()
        url = str(row.get("url", "")).strip()
        if not word or not url:
            continue
        heat_raw = row.get("hotTag")
        try:
            heat_value: int | None = int(heat_raw) if heat_raw is not None else None
        except (TypeError, ValueError):
            heat_value = None
        rank: int | None = None if row.get("isTop") else row.get("index")
        items.append(
            HotItem(
                item_id=f"baidu_word_{_safe_word_slug(word)}",
                platform="baidu",
                item_type="hotword",
                title=word,
                url=url,
                rank=int(rank) if isinstance(rank, (int, str)) and str(rank).isdigit() else None,
                heat=HeatMetrics(
                    value=heat_value,
                    label="" if heat_value is None else str(heat_value),
                    metric_name="hot_tag",
                    metrics={},
                ),
                summary="",
                category="baidu_hotword",
                matched_query_ids=matched_query_ids,
                fetched_at=fetched_at,
                fetch_status="success",
                raw_payload={"source_kind": "baidu_board", "raw": row},
            )
        )
    return items
```

- [ ] **Step 5: Run test to confirm it passes**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/providers/test_baidu_parsing.py::test_parse_board_returns_hotword_hot_items -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/providers/baidu.py tests/providers/test_baidu_parsing.py tests/providers/__init__.py
git commit -m "feat(baidu): add board response parser"
```

---

## Task 2: Search HTML parser (extract article IDs and titles)

**Files:**
- Modify: `src/heated_topics_v3/providers/baidu.py`
- Modify: `tests/providers/test_baidu_parsing.py`

- [ ] **Step 1: Add failing test for search parser**

Append to `tests/providers/test_baidu_parsing.py`:

```python
from heated_topics_v3.providers.baidu import parse_baidu_search_response


SEARCH_FIXTURE = """
<html><body>
<a href="https://baijiahao.baidu.com/s?id=1110000000000000001">携手推动人工智能</a>
<a href="https://baijiahao.baidu.com/s?id=2220000000000000002">百度热搜抓取工具</a>
<a href="https://example.com/something-else">unrelated</a>
<a href="https://baijiahao.baidu.com/s?id=1110000000000000001">dup</a>
</body></html>
"""


def test_parse_search_extracts_unique_baijiahao_links():
    articles = parse_baidu_search_response(SEARCH_FIXTURE, source_word="携手")
    assert [a.article_id for a in articles] == [
        "1110000000000000001",
        "2220000000000000002",
    ]
    assert articles[0].title == "携手推动人工智能"
    assert articles[1].title == "百度热搜抓取工具"
    assert all(a.platform == "baidu" for a in articles)
    assert all(a.source_word == "携手" for a in articles)


def test_parse_search_returns_empty_on_no_baijiahao():
    articles = parse_baidu_search_response(
        "<html><body>no article links here</body></html>",
        source_word="unused",
    )
    assert articles == []
```

- [ ] **Step 2: Run test to confirm it fails**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/providers/test_baidu_parsing.py::test_parse_search_extracts_unique_baijiahao_links tests/providers/test_baidu_parsing.py::test_parse_search_returns_empty_on_no_baijiahao -v
```
Expected: FAIL with `ImportError: cannot import name 'parse_baidu_search_response'`.

- [ ] **Step 3: Implement search parser**

Append to `src/heated_topics_v3/providers/baidu.py`:

```python
@dataclass(frozen=True)
class BaiduSearchArticle:
    article_id: str
    title: str
    url: str
    source_word: str


_BJH_HREF_RE = __import__("re").compile(
    r"baijiahao\.baidu\.com/s\?id=([A-Za-z0-9_\-]+)"
)


class _SearchLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_anchor = False
        self._href: str | None = None
        self._current_parts: list[str] = []
        self._found: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = next((v for k, v in attrs if k == "href" and v), "")
        if _BJH_HREF_RE.search(href):
            self._in_anchor = True
            self._href = href
            self._current_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_anchor:
            title = " ".join("".join(self._current_parts).split())
            if title and self._href:
                self._found.append((self._href, title))
            self._in_anchor = False
            self._href = None
            self._current_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._current_parts.append(data)

    def result(self) -> list[tuple[str, str]]:
        return self._found


def parse_baidu_search_response(
    response_text: str,
    source_word: str,
) -> list[BaiduSearchArticle]:
    parser = _SearchLinkParser()
    parser.feed(response_text)
    seen: set[str] = set()
    out: list[BaiduSearchArticle] = []
    for href, title in parser.result():
        m = _BJH_HREF_RE.search(href)
        if not m:
            continue
        article_id = m.group(1)
        if article_id in seen:
            continue
        seen.add(article_id)
        url = f"https://baijiahao.baidu.com/s?id={article_id}"
        out.append(
            BaiduSearchArticle(
                article_id=article_id,
                title=title,
                url=url,
                source_word=source_word,
            )
        )
    return out
```

Make sure the imports at the top of `baidu.py` cover what was added: `from dataclasses import dataclass`, and `import hashlib` is already there.

- [ ] **Step 4: Run test to confirm it passes**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/providers/test_baidu_parsing.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/providers/baidu.py tests/providers/test_baidu_parsing.py
git commit -m "feat(baidu): add search HTML parser"
```

---

## Task 3: Article HTML body parser

**Files:**
- Modify: `src/heated_topics_v3/providers/baidu.py`
- Modify: `tests/providers/test_baidu_parsing.py`

- [ ] **Step 1: Add failing test for article parser**

Append to `tests/providers/test_baidu_parsing.py`:

```python
from heated_topics_v3.providers.baidu import parse_baidu_article_response


ARTICLE_HTML = """
<html><body>
<article>
<p>第一段：背景介绍。</p>
<p>第二段：核心观点。</p>
<style>.x{}</style>
</article>
<div>页面其它内容，应当被忽略。</div>
</body></html>
"""


def test_parse_article_extracts_paragraph_text_and_excludes_style():
    detail = parse_baidu_article_response(
        ARTICLE_HTML,
        item_id="baidu_article_111",
        item_url="https://baijiahao.baidu.com/s?id=111",
        fetched_at="2026-07-19T20:00:00+08:00",
    )
    assert detail.item_id == "baidu_article_111"
    assert detail.url == "https://baijiahao.baidu.com/s?id=111"
    assert detail.platform == "baidu"
    assert detail.extraction_method == "baijiahao_article_page"
    assert detail.fetch_status == "success"
    assert "第一段" in detail.content
    assert "第二段" in detail.content
    assert "页面其它内容" not in detail.content
    assert ".x{}" not in detail.content  # style block excluded


def test_parse_article_returns_empty_when_no_article_tag():
    detail = parse_baidu_article_response(
        "<html><body>no article</body></html>",
        item_id="baidu_article_222",
        item_url="https://baijiahao.baidu.com/s?id=222",
        fetched_at="2026-07-19T20:00:00+08:00",
    )
    assert detail.fetch_status == "empty"
    assert detail.content == ""
```

- [ ] **Step 2: Run test to confirm it fails**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/providers/test_baidu_parsing.py::test_parse_article_extracts_paragraph_text_and_excludes_style tests/providers/test_baidu_parsing.py::test_parse_article_returns_empty_when_no_article_tag -v
```
Expected: FAIL with `ImportError: cannot import name 'parse_baidu_article_response'`.

- [ ] **Step 3: Implement article parser**

Append to `src/heated_topics_v3/providers/baidu.py`:

```python
class _BaijiahaoArticleParser(HTMLParser):
    """Pull concatenated <p> text inside the first <article> tag, skip <script>/<style>."""

    def __init__(self) -> None:
        super().__init__()
        self._in_article = False
        self._depth = 0
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_article and tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "article":
            self._in_article = True
            self._depth = 1
            return
        if self._in_article:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            if tag in {"script", "style"}:
                self._ignored_depth -= 1
            return
        if self._in_article:
            self._depth -= 1
            if self._depth <= 0:
                self._in_article = False

    def handle_data(self, data: str) -> None:
        if self._in_article and not self._ignored_depth:
            text = " ".join(data.split())
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


def parse_baidu_article_response(
    response_text: str,
    item_id: str,
    item_url: str,
    fetched_at: str,
) -> ItemDetail:
    parser = _BaijiahaoArticleParser()
    parser.feed(response_text)
    content = parser.text()
    status = "success" if content else "empty"
    return ItemDetail(
        item_id=item_id,
        platform="baidu",
        url=item_url,
        title="",
        author="",
        content=content,
        published_at="",
        tags=(),
        extraction_method="baijiahao_article_page",
        fetch_status=status,
        raw_payload={"html_length": len(response_text)},
    )
```

- [ ] **Step 4: Run test to confirm it passes**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/providers/test_baidu_parsing.py -v
```
Expected: PASS (5 tests total).

- [ ] **Step 5: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/providers/baidu.py tests/providers/test_baidu_parsing.py
git commit -m "feat(baidu): add article HTML body parser"
```

---

## Task 4: Cache helpers — board (daily) and search (per-word) and article (per-id)

**Files:**
- Create: `src/heated_topics_v3/baidu_cache.py`
- Create: `tests/test_baidu_cache.py`

- [ ] **Step 1: Write failing test covering all three caches**

In `tests/test_baidu_cache.py`:

```python
import json
import os
import time
from pathlib import Path

import pytest

from heated_topics_v3.baidu_cache import (
    get_or_fetch_board,
    get_or_fetch_board_with_record,
    get_or_fetch_search,
    get_or_fetch_search_with_record,
    get_or_fetch_article,
    get_or_fetch_article_with_record,
)


def test_board_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    fetched: list[str] = []

    def fetcher(date: str) -> dict:
        fetched.append(date)
        return {"date": date, "raw": "<json>"}

    cache_root = tmp_path
    payload, src1 = get_or_fetch_board(cache_root, "2026-07-19", fetcher)
    assert payload == {"date": "2026-07-19", "raw": "<json>"}
    assert src1 == "fresh"
    payload2, src2 = get_or_fetch_board(cache_root, "2026-07-19", fetcher)
    assert payload2 == payload
    assert src2 == "cache"
    assert len(fetched) == 1


def test_search_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    fetched: list[str] = []

    def fetcher(word: str) -> dict:
        fetched.append(word)
        return {"word": word, "ids": ["1", "2"]}

    out, src1 = get_or_fetch_search(tmp_path, "2026-07-19", "携手", fetcher)
    assert out == {"word": "携手", "ids": ["1", "2"]}
    assert src1 == "fresh"
    out2, src2 = get_or_fetch_search(tmp_path, "2026-07-19", "携手", fetcher)
    assert out2 == out
    assert src2 == "cache"
    assert len(fetched) == 1


def test_article_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    fetched: list[str] = []

    def fetcher(article_id: str) -> dict:
        fetched.append(article_id)
        return {"article_id": article_id, "chars": 123}

    out, src1 = get_or_fetch_article(tmp_path, "2026-07-19", "111", fetcher)
    assert src1 == "fresh"
    out2, src2 = get_or_fetch_article(tmp_path, "2026-07-19", "111", fetcher)
    assert src2 == "cache"
    assert len(fetched) == 1


def test_search_cache_lock_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If the lock is held beyond deadline, function returns empty and 'lock_timeout'."""
    cache_path = tmp_path / "baidu" / "search" / "2026-07-19"
    cache_path.mkdir(parents=True, exist_ok=True)
    # Create a fake lock file to simulate a concurrent holder.
    word = "abc"
    digest_sha = _expected_digest(word)
    (cache_path / f"{digest_sha}.lock").write_text("held", encoding="utf-8")

    def fetcher(word: str) -> dict:  # pragma: no cover
        return {"word": word}

    out, src = get_or_fetch_search_with_record(
        tmp_path,
        "2026-07-19",
        word,
        fetcher,
        lock_wait_seconds=0.0,
        deadline=time.monotonic() + 0.05,
    )
    assert src == "lock_timeout"
    assert out == []


def _expected_digest(word: str) -> str:
    # Mirror the digest logic: sha256 of normalized word. Import the helper from
    # the module under test if you want to be exact; this is a quick sanity
    # stub for the lock-only test path.
    import hashlib
    return hashlib.sha256(word.encode("utf-8")).hexdigest()
```

- [ ] **Step 2: Run test to confirm it fails**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_cache.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'heated_topics_v3.baidu_cache'`.

- [ ] **Step 3: Implement `baidu_cache.py`**

Write `src/heated_topics_v3/baidu_cache.py`:

```python
"""Daily single-flight caches for Baidu hot-word / search / article fetches.

Mirrors the design of `toutiao_search_cache.py`:

- File-based advisory lock (`<cache>.lock`) for cross-process coordination.
- atomic write via temp + `Path.replace`.
- `schema_version` in each payload for forward-compatible upgrades.
- Returns `(<value>, source)` where source ∈ {"cache", "cache_after_wait",
  "fresh", "deadline_exceeded", "lock_timeout"}.

Each public function has a `_with_record` sibling that exposes the source
string — the pipeline uses the simple form, tests use the recorded form.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

BOARD_SUBDIR = "baidu/board"
SEARCH_SUBDIR = "baidu/search"
ARTICLE_SUBDIR = "baidu/articles"


# ---- low-level helpers ----

def _acquire_lock_nonblocking(lock_path: Path) -> int | None:
    try:
        return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def _release_lock(lock_path: Path, fd: int) -> None:
    try:
        os.close(fd)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _normalize_word(word: str) -> str:
    return " ".join(str(word).split())


def _word_digest(word: str) -> str:
    return hashlib.sha256(_normalize_word(word).encode("utf-8")).hexdigest()


def _load_payload(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".baidu_cache_", suffix=".json", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _single_flight(
    *,
    cache_path: Path,
    deadline: float | None,
    lock_wait_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    load_cached: Callable[[], Any | None],
    save_cached: Callable[[Any], None],
    live_fetch: Callable[[float], Any],
) -> tuple[Any, str]:
    cached = load_cached()
    if cached is not None:
        return cached, "cache"

    now = monotonic()
    if deadline is not None and now >= deadline:
        return _empty_for(save_cached), "deadline_exceeded"

    lock_path = cache_path.with_suffix(".lock")
    wait_deadline = now + max(0.0, lock_wait_seconds)
    if deadline is not None:
        wait_deadline = min(wait_deadline, deadline)

    lock_fd: int | None = None
    while True:
        lock_fd = _acquire_lock_nonblocking(lock_path)
        if lock_fd is not None:
            break
        now = monotonic()
        if now >= wait_deadline:
            return _empty_for(save_cached), "lock_timeout"
        sleep(min(0.02, wait_deadline - now))

    try:
        cached = load_cached()
        if cached is not None:
            return cached, "cache_after_wait"

        now = monotonic()
        if deadline is not None and now >= deadline:
            return _empty_for(save_cached), "deadline_exceeded"
        remaining = float("inf") if deadline is None else deadline - now
        try:
            result = live_fetch(remaining)
        except Exception:
            return _empty_for(save_cached), "fetch_error"
        try:
            save_cached(result)
        except (OSError, TypeError, ValueError):
            pass
        return result, "fresh"
    finally:
        if lock_fd is not None:
            _release_lock(lock_path, lock_fd)


def _empty_for(save_cached: Callable[[Any], None]) -> Any:
    """Return the appropriate empty value for the caller — board returns dict,
    search returns list, article returns dict."""
    # Sentinel via attribute lookup
    return getattr(save_cached, "_empty_marker", None)


# ---- board (date key) ----

def _board_path(cache_root: Path | str, date: str) -> Path:
    return Path(cache_root) / BOARD_SUBDIR / f"{date}.json"


def get_or_fetch_board_with_record(
    cache_root: Path | str,
    date: str,
    fetch_live: Callable[[str], dict],
    *,
    deadline: float | None = None,
    lock_wait_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict, str]:
    path = _board_path(cache_root, date)

    def load_cached() -> dict | None:
        payload = _load_payload(path)
        if not payload:
            return None
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if payload.get("date") != date:
            return None
        return payload

    def save_cached(value: dict) -> None:
        if not isinstance(value, dict) or not value:
            return
        payload = {"schema_version": SCHEMA_VERSION, "date": date, **value}
        _atomic_write_json(path, payload)

    save_cached._empty_marker = {}  # type: ignore[attr-defined]

    return _single_flight(
        cache_path=path,
        deadline=deadline,
        lock_wait_seconds=lock_wait_seconds,
        monotonic=monotonic,
        sleep=sleep,
        load_cached=load_cached,
        save_cached=save_cached,
        live_fetch=lambda remaining: fetch_live(date),
    )


def get_or_fetch_board(
    cache_root: Path | str,
    date: str,
    fetch_live: Callable[[str], dict],
    **kwargs: Any,
) -> dict:
    return get_or_fetch_board_with_record(cache_root, date, fetch_live, **kwargs)[0]


# ---- search (per-word key) ----

def _search_path(cache_root: Path | str, date: str, word: str) -> Path:
    return Path(cache_root) / SEARCH_SUBDIR / date / f"{_word_digest(word)}.json"


def get_or_fetch_search_with_record(
    cache_root: Path | str,
    date: str,
    word: str,
    fetch_live: Callable[[str], list],
    *,
    deadline: float | None = None,
    lock_wait_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list, str]:
    path = _search_path(cache_root, date, word)

    def load_cached() -> list | None:
        payload = _load_payload(path)
        if not payload:
            return None
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if payload.get("date") != date:
            return None
        if payload.get("word") != _normalize_word(word):
            return None
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids:
            return None
        return ids

    def save_cached(value: list) -> None:
        if not isinstance(value, list) or not value:
            return
        payload = {
            "schema_version": SCHEMA_VERSION,
            "date": date,
            "word": _normalize_word(word),
            "ids": value,
        }
        _atomic_write_json(path, payload)

    save_cached._empty_marker = []  # type: ignore[attr-defined]

    return _single_flight(
        cache_path=path,
        deadline=deadline,
        lock_wait_seconds=lock_wait_seconds,
        monotonic=monotonic,
        sleep=sleep,
        load_cached=load_cached,
        save_cached=save_cached,
        live_fetch=lambda remaining: fetch_live(word),
    )


def get_or_fetch_search(
    cache_root: Path | str,
    date: str,
    word: str,
    fetch_live: Callable[[str], list],
    **kwargs: Any,
) -> list:
    return get_or_fetch_search_with_record(cache_root, date, word, fetch_live, **kwargs)[0]


# ---- article (per-id key) ----

def _article_path(cache_root: Path | str, date: str, article_id: str) -> Path:
    return Path(cache_root) / ARTICLE_SUBDIR / date / f"{article_id}.json"


def get_or_fetch_article_with_record(
    cache_root: Path | str,
    date: str,
    article_id: str,
    fetch_live: Callable[[str], dict],
    *,
    deadline: float | None = None,
    lock_wait_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict, str]:
    path = _article_path(cache_root, date, article_id)

    def load_cached() -> dict | None:
        payload = _load_payload(path)
        if not payload:
            return None
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        if payload.get("date") != date:
            return None
        if payload.get("article_id") != article_id:
            return None
        return payload

    def save_cached(value: dict) -> None:
        if not isinstance(value, dict) or not value:
            return
        payload = {
            "schema_version": SCHEMA_VERSION,
            "date": date,
            "article_id": article_id,
            **value,
        }
        _atomic_write_json(path, payload)

    save_cached._empty_marker = {}  # type: ignore[attr-defined]

    return _single_flight(
        cache_path=path,
        deadline=deadline,
        lock_wait_seconds=lock_wait_seconds,
        monotonic=monotonic,
        sleep=sleep,
        load_cached=load_cached,
        save_cached=save_cached,
        live_fetch=lambda remaining: fetch_live(article_id),
    )


def get_or_fetch_article(
    cache_root: Path | str,
    date: str,
    article_id: str,
    fetch_live: Callable[[str], dict],
    **kwargs: Any,
) -> dict:
    return get_or_fetch_article_with_record(cache_root, date, article_id, fetch_live, **kwargs)[0]
```

- [ ] **Step 4: Run test to confirm it passes**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_cache.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/baidu_cache.py tests/test_baidu_cache.py
git commit -m "feat(baidu): add single-flight daily caches for board/search/article"
```

---

## Task 5: Pipeline entry — `run_baidu_pipeline`

**Files:**
- Modify: `src/heated_topics_v3/providers/baidu.py` (add `fetch_baidu_hot_items` + `fetch_baidu_item_detail`)
- Modify: `src/heated_topics_v3/pipeline.py`
- Test: `tests/test_baidu_pipeline.py`

- [ ] **Step 1: Write failing pipeline test**

In `tests/test_baidu_pipeline.py`:

```python
import json
from pathlib import Path

from heated_topics_v3.pipeline import run_baidu_pipeline


def test_run_baidu_pipeline_writes_dataset_and_report(tmp_path: Path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech", "ai"],
                "audience": ["developers"],
                "content_modes": ["tutorial", "analysis"],
                "preferred_platforms": ["baidu"],
                "core_keywords": ["AI Agent", "MCP"],
                "entity_keywords": ["Claude Code"],
                "excluded_keywords": [],
            }
        ),
        encoding="utf-8",
    )

    board_json = json.dumps(
        {
            "success": True,
            "data": {"cards": [{"component": "tabTextList", "content": [
                {"content": [
                    {"isTop": True, "word": "AI Agent 发布", "url": "https://m.baidu.com/s?word=AI-Agent"},
                    {"isTop": False, "index": 1, "word": "MCP 全景", "url": "https://m.baidu.com/s?word=MCP", "hotTag": "3"},
                    {"isTop": False, "index": 2, "word": "无关新闻", "url": "https://m.baidu.com/s?word=other", "hotTag": "1"},
                ]}
            ]}]},
        },
        ensure_ascii=False,
    )

    search_html = """
<html><body>
<a href="https://baijiahao.baidu.com/s?id=1110000000000000001">AI Agent 实战</a>
<a href="https://baijiahao.baidu.com/s?id=2220000000000000002">MCP 工具集</a>
</body></html>
"""

    article_html = """
<html><body>
<article>
<p>这是一篇关于 AI Agent 的实战文章。</p>
<p>本文详细讨论了 MCP 协议的工作方式。</p>
</article>
</body></html>
"""

    def board_fetcher(url: str, timeout_seconds: int) -> str:
        return board_json

    def search_fetcher(url: str, timeout_seconds: int) -> str:
        return search_html

    def article_fetcher(url: str, timeout_seconds: int) -> str:
        return article_html

    outputs = run_baidu_pipeline(
        profile_path=profile_path,
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-19T20:00:00+08:00",
        cache_root=tmp_path / "cache",
        top_n=10,
        fetcher=board_fetcher,
        search_fetcher=search_fetcher,
        article_fetcher=article_fetcher,
    )

    run_dir = tmp_path / "outputs" / "tech_ai_creator" / "baidu" / "run_20260719_200000"
    assert set(outputs) == {"article_texts", "hot_items", "report"}
    assert outputs["hot_items"].parent == run_dir
    assert outputs["report"].name == "report.md"
    assert outputs["hot_items"].name == "hot_items.json"

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    text_files = sorted(outputs["article_texts"].glob("*.txt"))

    # Two words matched core keywords: "AI Agent 发布" and "MCP 全景".
    # Each yields one baijiahao article; "无关新闻" matches nothing.
    assert len(hot_items) == 2
    titles = [row["item"]["title"] for row in hot_items]
    assert titles == ["AI Agent 发布", "MCP 全景"]
    for row in hot_items:
        assert row["detail"]["fetch_status"] == "success"
        assert row["detail"]["extraction_method"] == "baijiahao_article_page"
        assert row["detail"]["txt_path"].startswith("article_texts/")
    assert len(text_files) == 2

    report = outputs["report"].read_text(encoding="utf-8")
    assert "# Baidu 热搜日报" in report
    assert "AI Agent 发布" in report
    assert "MCP 全景" in report


def test_run_baidu_pipeline_is_all_transparent_when_no_match(tmp_path: Path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech"],
                "audience": ["devs"],
                "content_modes": ["tutorial"],
                "preferred_platforms": ["baidu"],
                "core_keywords": ["NoSuchWord"],
                "entity_keywords": [],
                "excluded_keywords": [],
            }
        ),
        encoding="utf-8",
    )

    board_json = json.dumps(
        {"success": True, "data": {"cards": [{"component": "tabTextList", "content": [
            {"content": [{"isTop": True, "word": "无关新闻", "url": "https://m.baidu.com/s?word=other"}]}
        ]}]}},
        ensure_ascii=False,
    )

    outputs = run_baidu_pipeline(
        profile_path=profile_path,
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-19T20:00:00+08:00",
        cache_root=tmp_path / "cache",
        fetcher=lambda u, t: board_json,
        search_fetcher=lambda u, t: "<html></html>",
        article_fetcher=lambda u, t: "<html></html>",
    )

    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert hot_items == []
    report = outputs["report"].read_text(encoding="utf-8")
    assert "本次未抓到任何条目" in report
```

- [ ] **Step 2: Run test to confirm it fails**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_pipeline.py -v
```
Expected: FAIL with `ImportError: cannot import name 'run_baidu_pipeline'`.

- [ ] **Step 3: Add fetcher wrappers to providers/baidu.py**

Append to `src/heated_topics_v3/providers/baidu.py`:

```python
from collections.abc import Callable
from heated_topics_v3.contracts import ItemDetail  # (already at top)


BOARD_URL = "https://top.baidu.com/api/board?platform=wise&page=realtime"
SEARCH_URL_TEMPLATE = "https://m.baidu.com/s?word={word}"
ARTICLE_URL_TEMPLATE = "https://baijiahao.baidu.com/s?id={article_id}"


def fetch_baidu_board_text(
    fetcher: Callable[[str, int], str],
    timeout_seconds: int = 15,
) -> str:
    return fetcher(BOARD_URL, timeout_seconds)


def fetch_baidu_search_text(
    word: str,
    fetcher: Callable[[str, int], str],
    timeout_seconds: int = 15,
) -> str:
    encoded = __import__("urllib.parse").parse.quote(word)
    return fetcher(SEARCH_URL_TEMPLATE.format(word=encoded), timeout_seconds)


def fetch_baidu_article_text(
    article_id: str,
    fetcher: Callable[[str, int], str],
    timeout_seconds: int = 20,
) -> str:
    return fetcher(ARTICLE_URL_TEMPLATE.format(article_id=article_id), timeout_seconds)
```

- [ ] **Step 4: Add `run_baidu_pipeline` to pipeline.py**

Add to the imports at the top of `src/heated_topics_v3/pipeline.py`:

```python
from heated_topics_v3.providers.baidu import (
    BaiduSearchArticle,
    fetch_baidu_article_text,
    fetch_baidu_board_text,
    fetch_baidu_search_text,
    parse_baidu_article_response,
    parse_baidu_board_response,
    parse_baidu_search_response,
)
from heated_topics_v3.baidu_cache import (
    get_or_fetch_article_with_record,
    get_or_fetch_board_with_record,
    get_or_fetch_search_with_record,
)
```

Append near the existing `run_juejin_pipeline` (after `def run_juejin_pipeline` and before `_run_platform_pipeline`):

```python
def run_baidu_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    search_fetcher: Callable[[str, int], str] | None = None,
    article_fetcher: Callable[[str, int], str] | None = None,
    top_n: int = 30,
    offline: bool = False,
    force_board_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
) -> dict[str, Path]:
    profile = load_user_profile(profile_path)
    board_fetch = fetcher or _fetch_text_default
    search_fetch = search_fetcher or board_fetch
    article_fetch = article_fetcher or board_fetch

    from heated_topics_v3.hot_board_cache import utc8_today
    today = utc8_today()
    cache_root_path = Path(cache_root)

    # ---- stage 1: board ----
    def live_board(_date: str) -> dict:
        text = fetch_baidu_board_text(board_fetch)
        return {"response_text": text}

    if offline and not force_board_refresh:
        cached = get_or_fetch_board_with_record(
            cache_root_path, today, lambda d: live_board(d), deadline=time.monotonic()
        )
        body = ""
        if isinstance(cached, dict) and isinstance(cuted := cached, dict):
            body = str(cuted.get("response_text", ""))
    elif force_board_refresh:
        body = fetch_baidu_board_text(board_fetch)
        get_or_fetch_board_with_record(
            cache_root_path, today, lambda d: {"response_text": body}
        )
    else:
        payload, _src = get_or_fetch_board_with_record(
            cache_root_path, today, live_board
        )
        body = str(payload.get("response_text", "")) if isinstance(payload, dict) else ""
    hot_words: list[HotItem] = parse_baidu_board_response(
        body, fetched_at=fetched_at, matched_query_ids=matched_query_ids
    )

    # ---- stage 2: per-word search ----
    expanded: list[HotItem] = []
    for word_item in hot_words[:top_n]:
        word = word_item.title

        def live_search(_w: str = word) -> list:
            html = fetch_baidu_search_text(word, search_fetch)
            articles = parse_baidu_search_response(html, source_word=word)
            return [
                {
                    "article_id": a.article_id,
                    "title": a.title,
                    "url": a.url,
                    "source_word": a.source_word,
                }
                for a in articles
            ]

        if offline:
            ids_payload, src = get_or_fetch_search_with_record(
                cache_root_path,
                today,
                word,
                live_search,
                deadline=time.monotonic(),
            )
        else:
            ids_payload, src = get_or_fetch_search_with_record(
                cache_root_path, today, word, live_search
            )
        if not isinstance(ids_payload, list):
            continue
        for entry in ids_payload:
            if not isinstance(entry, dict):
                continue
            article_id = str(entry.get("article_id", ""))
            title = str(entry.get("title", ""))
            url = str(entry.get("url", ""))
            if not article_id:
                continue
            expanded.append(
                HotItem(
                    item_id=f"baidu_article_{article_id}",
                    platform="baidu",
                    item_type="article",
                    title=title or word,
                    url=url,
                    rank=None,
                    heat=HeatMetrics(value=None, label="", metric_name="search_recall", metrics={}),
                    summary="",
                    category="baijiahao",
                    matched_query_ids=matched_query_ids,
                    fetched_at=fetched_at,
                    fetch_status="success",
                    raw_payload={
                        "source_kind": "baidu_search_recall",
                        "source_word": word,
                        "source_word_url": word_item.url,
                        "article_id": article_id,
                    },
                )
            )

    # ---- matching ----
    queries = tuple(build_topic_queries(profile))
    matches = [
        result
        for item in expanded
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]

    # ---- stage 3: per-article body ----
    item_details: list[ItemDetail] = []
    for match in matches:
        item = match.item
        article_id = str(item.raw_payload.get("article_id", ""))

        def live_article(_aid: str = article_id) -> dict:
            html = fetch_baidu_article_text(article_id, article_fetch)
            detail = parse_baidu_article_response(
                html,
                item_id=item.item_id,
                item_url=item.url,
                fetched_at=fetched_at,
            )
            return {
                "title": item.title,
                "content": detail.content,
                "extraction_method": detail.extraction_method,
                "fetch_status": detail.fetch_status,
                "html_length": len(html),
            }

        if offline:
            payload, _src = get_or_fetch_article_with_record(
                cache_root_path,
                today,
                article_id,
                live_article,
                deadline=time.monotonic(),
            )
        else:
            payload, _src = get_or_fetch_article_with_record(
                cache_root_path, today, article_id, live_article
            )
        if not isinstance(payload, dict) or not payload:
            detail = ItemDetail(
                item_id=item.item_id,
                platform=item.platform,
                url=item.url,
                title=item.title,
                author="",
                content="",
                published_at="",
                tags=(),
                extraction_method="baijiahao_article_page",
                fetch_status="empty",
                raw_payload={"html_length": 0},
            )
        else:
            content = str(payload.get("content", ""))
            detail = ItemDetail(
                item_id=item.item_id,
                platform=item.platform,
                url=item.url,
                title=str(payload.get("title", item.title)),
                author="",
                content=content,
                published_at="",
                tags=(),
                extraction_method=str(payload.get("extraction_method", "baijiahao_article_page")),
                fetch_status=str(payload.get("fetch_status", "success" if content else "empty")),
                raw_payload={"html_length": int(payload.get("html_length", 0) or 0)},
            )
        item_details.append(detail)

    return _run_platform_pipeline(
        profile_path=profile_path,
        output_root=output_root,
        fetched_at=fetched_at,
        source_id="baidu",
        hot_items_fetcher=lambda fa: expanded,
        item_detail_fetcher=lambda _it, _details=item_details: _details_for_items(_details, matches),
        report_renderer=render_baidu_report,
    )


def _fetch_text_default(url: str, timeout_seconds: int = 15) -> str:
    raise RuntimeError(
        f"Baidu fetcher not provided and live mode unavailable for {url}"
    )


def _details_for_items(details: list[ItemDetail], matches) -> list[ItemDetail]:
    """No-op helper: kept to make the pipeline interface mirror juejin.

    The actual detail lookup happens via `match.item` -> detail keyed by
    item_id inside `_build_hot_item_rows`. Exists only for signature parity.
    """
    return details
```

Note: the calls into `_run_platform_pipeline` reuse the existing Juejin pattern.
Adjust the `source_id` if needed (it should already be `"baidu"`).

- [ ] **Step 5: Run test to confirm it passes**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_pipeline.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/providers/baidu.py src/heated_topics_v3/pipeline.py tests/test_baidu_pipeline.py
git commit -m "feat(baidu): add run_baidu_pipeline + fetch wrappers"
```

---

## Task 6: Report renderer

**Files:**
- Modify: `src/heated_topics_v3/reporting.py`
- Modify: `tests/test_baidu_pipeline.py` (assertion already included)

- [ ] **Step 1: Confirm report test is failing due to missing renderer**

Re-run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_pipeline.py -v
```
Expected: the renderer line is the only thing failing (the assertions we wrote test for `"# Baidu 热搜日报"` and `"本次未抓到任何条目"`).

If the test already passes from Task 5, fix the task ordering by reading the import error and implementing this task first. Skip steps that don't apply.

- [ ] **Step 2: Add `render_baidu_report` to reporting.py**

Append to `src/heated_topics_v3/reporting.py`:

```python
def render_baidu_report(
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    return _render_platform_report("Baidu 热搜日报", profile, matches, fetched_at, item_details)
```

- [ ] **Step 3: Re-run tests to confirm**

```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_pipeline.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/reporting.py
git commit -m "feat(baidu): add render_baidu_report"
```

---

## Task 7: CLI subcommand `baidu`

**Files:**
- Modify: `src/heated_topics_v3/cli.py`

- [ ] **Step 1: Add `_add_baidu_args`, `_handle_baidu`, and `baidu` subparser**

Edit `src/heated_topics_v3/cli.py`:

1. Add to imports near the top:

```python
from heated_topics_v3.pipeline import (
    run_baidu_pipeline,
    run_juejin_pipeline,
    run_toutiao_pipeline,
    run_toutiao_pipeline_v2,
)
from heated_topics_v3.reporting import render_baidu_report  # (already import the others; add this)
```

Replace `from heated_topics_v3.reporting import (...)` lines to include `render_baidu_report`.

2. Add subparser just after `toutiao = subparsers.add_parser("toutiao", ...)`:

```python
    baidu = subparsers.add_parser("baidu", help="Collect Baidu hot search and match it to a user profile.")
    _add_baidu_args(baidu)
```

3. Add `if args.command == "baidu":` branch inside `_main`, just after the `toutiao` branch:

```python
    if args.command == "baidu":
        _handle_baidu(args)
```

4. Add the helper functions near the bottom (after `_handle_refresh_keywords`):

```python
def _add_baidu_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--top-n", dest="top_n", default=30, type=int)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force-board-refresh", dest="force_board_refresh", action="store_true")
    parser.add_argument("--matched-query-ids", dest="matched_query_ids", action="append", default=[])


def _handle_baidu(args) -> None:
    fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    matched_query_ids = tuple(q.strip() for q in args.matched_query_ids if q.strip())
    outputs = run_baidu_pipeline(
        profile_path=args.profile,
        output_root=args.output_root,
        fetched_at=fetched_at,
        cache_root=args.cache_root,
        top_n=args.top_n,
        offline=args.offline,
        force_board_refresh=args.force_board_refresh,
        matched_query_ids=matched_query_ids,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")
```

- [ ] **Step 2: Smoke test CLI wiring**

Run:
```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run python -m heated_topics_v3.cli baidu --help
```
Expected: usage block listing `--profile`, `--cache-root`, `--top-n`, `--offline`, `--force-board-refresh`, `--matched-query-ids`, etc.

- [ ] **Step 3: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add src/heated_topics_v3/cli.py
git commit -m "feat(baidu): add baidu CLI subcommand"
```

---

## Task 8: Offline-mode integration test

**Files:**
- Create: `tests/test_baidu_offline.py`

- [ ] **Step 1: Write failing offline test**

```python
"""`--offline` must not touch the network when caches are absent."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from heated_topics_v3.pipeline import run_baidu_pipeline


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(
        json.dumps(
            {
                "profile_id": "tech_ai_creator",
                "display_name": "Tech AI Creator",
                "domains": ["tech"],
                "audience": ["devs"],
                "content_modes": ["tutorial"],
                "preferred_platforms": ["baidu"],
                "core_keywords": ["AI"],
                "entity_keywords": [],
                "excluded_keywords": [],
            }
        ),
        encoding="utf-8",
    )
    return p


def test_offline_with_empty_cache_emits_zero_network_calls(tmp_path: Path, profile_path: Path):
    blocked = {"calls": 0}

    def fail_urlopen(*a, **kw):  # pragma: no cover
        blocked["calls"] += 1
        raise AssertionError("offline mode must not call urlopen")

    # block both fetcher pathways used by the parser
    with patch("urllib.request.urlopen", side_effect=fail_urlopen):
        outputs = run_baidu_pipeline(
            profile_path=profile_path,
            output_root=tmp_path / "outputs",
            fetched_at="2026-07-19T20:00:00+08:00",
            cache_root=tmp_path / "cache",
            offline=True,
        )

    assert blocked["calls"] == 0
    report = outputs["report"].read_text(encoding="utf-8")
    assert "本次未抓到任何条目" in report
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert hot_items == []
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_offline.py -v
```
Expected: FAIL with assertion or network call (depending on whether the existing fetcher call goes through urlopen).

- [ ] **Step 3: Confirm `run_baidu_pipeline` reaches no fetcher in offline mode with empty cache**

Inspect Task 5 step 4: the pipeline already calls `get_or_fetch_board_with_record(..., deadline=...)`. With an empty cache and a `deadline` already past, the function returns immediately. The `_fetch_text_default` is only invoked by `fetcher` when no fetcher was provided; the test does not pass `fetcher`, so it relies on the existing offline branch behavior. If the test still calls urlopen, ensure no live fetcher is constructed by adjusting the pipeline's offline handling — but with the Task 5 implementation, no fetcher call should happen.

If after inspection the test still fails, modify `run_baidu_pipeline` so the offline branch:
- never instantiates `_fetch_text_default` when fetcher is None, and
- early-returns empty results from each cache.

Document the change in the implementation commit message.

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest tests/test_baidu_offline.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add tests/test_baidu_offline.py
git commit -m "test(baidu): add offline-mode zero-network test"
```

---

## Task 9: Documentation updates

**Files:**
- Modify: `docs/specs/platform-hot-list-matrix.md`
- Modify: `README.md`

- [ ] **Step 1: Update the matrix**

In `docs/specs/platform-hot-list-matrix.md`, replace the `baidu` bullet:

```markdown
First batch:

1. `juejin`
2. `bilibili`
3. `baidu` — implemented as the Baidu 热搜 source. Hot words come from `https://top.baidu.com/api/board?platform=wise&page=realtime`; per-word recall and article body follow via mobile Baidu search and baijiahao.baidu.com. See `docs/superpowers/specs/2026-07-19-baidu-hotword-source-design.md`.
```

- [ ] **Step 2: Add Baidu command example in README**

Find the existing `juejin` / `toutiao` command examples in `README.md` and add a parallel block:

```markdown
### Baidu 热搜

```powershell
cd E:\.code\My\heatedTopics-V3
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli baidu `
  --profile config\profiles\tech_ai_creator.json `
  --output-root outputs `
  --cache-root cache `
  --top-n 30
```

Outputs land in `outputs/<profile>/baidu/run_<ts>/` (same layout as `juejin`).
```

- [ ] **Step 3: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add docs/specs/platform-hot-list-matrix.md README.md
git commit -m "docs(baidu): update hot-list matrix + README"
```

---

## Task 10: Cleanup reconnaissance probes

**Files:**
- Delete: `scripts/probe_baijiahao.py`
- Delete: `scripts/probe_baijiahao_m.py`
- Delete: `scripts/probe_baijiahao_api.py`
- Delete: `scripts/probe_baijiahao_api_v2.py`
- Delete: `scripts/probe_baijiahao_search.py`
- Create: `scripts/probe_baidu_board.py` (replacement reference)

- [ ] **Step 1: Write the kept reference probe**

Create `scripts/probe_baidu_board.py`:

```python
"""Reference probe kept after Baidu hot-word source implementation.

Captures the discovery path that landed on
`https://top.baidu.com/api/board?platform=wise&page=realtime` plus the
secondary endpoints used during planning:

- `https://m.baidu.com/s?word=<encoded>` — mobile Baidu search page.
  Heavily rate-limited; expect ~1 captcha per request after a few calls.
- `https://baijiahao.baidu.com/s?id=<id>` — article page; HTML is large
  but well-structured for `parse_baidu_article_response` to consume.

Usage:
    PYTHONPATH=src uv run python scripts/probe_baidu_board.py

This is a diagnostic, not a feature. Its existence is documented in
`docs/superpowers/specs/2026-07-19-baidu-hotword-source-design.md`.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
BOARD_URL = "https://top.baidu.com/api/board?platform=wise&page=realtime"


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "tmp" / "baidu_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(BOARD_URL, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    snapshot = out_dir / f"board_{int(time.time())}.json"
    snapshot.write_text(body, encoding="utf-8")
    print(f"snapshot: {snapshot}")
    print(json.dumps(json.loads(body)["data"]["cards"][0]["content"][0]["content"][:3], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Delete the legacy probes**

```bash
cd E:\.code\My\heatedTopics-V3
rm scripts/probe_baijiahao.py \
   scripts/probe_baijiahao_m.py \
   scripts/probe_baijiahao_api.py \
   scripts/probe_baijiahao_api_v2.py \
   scripts/probe_baijiahao_search.py
```

- [ ] **Step 3: Smoke test the kept probe**

```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run python scripts/probe_baidu_board.py
```
Expected: writes one JSON snapshot to `tmp/baidu_probe/board_*.json` and prints 3 entries.

- [ ] **Step 4: Commit**

```bash
cd E:\.code\My\heatedTopics-V3
git add scripts/probe_baidu_board.py
git rm scripts/probe_baijiahao.py scripts/probe_baijiahao_m.py scripts/probe_baijiahao_api.py scripts/probe_baijiahao_api_v2.py scripts/probe_baijiahao_search.py
git commit -m "chore(baidu): consolidate reconnaissance probes into single reference script"
```

---

## Task 11: Final full-suite verification

**Files:** none

- [ ] **Step 1: Run the project-wide pytest**

```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest -q
```
Expected: PASS for every test. No previously-green test should regress.

- [ ] **Step 2: Run the project lint/type hooks if defined**

Per `CLAUDE.md`, only the project-defined verification commands are authoritative. Run them and confirm green:

```bash
cd E:\.code\My\heatedTopics-V3
PYTHONPATH=src uv run pytest -q
```

- [ ] **Step 3: Manual CLI smoke (optional, behind user permission)**

Only with explicit user approval, run the CLI against `tech_ai_creator.json`:

```bash
cd E:\.code\My\heatedTopics-V3
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli baidu `
  --profile config\profiles\tech_ai_creator.json `
  --output-root outputs `
  --cache-root cache `
  --top-n 5
```

Then inspect `outputs/tech_ai_creator/baidu/run_*/report.md` and `hot_items.json`.

If the user declines this step, skip and report "all unit and integration tests green; live CLI run deferred to user."

- [ ] **Step 4: Commit any final fix-ups (only if needed)**

```bash
cd E:\.code\My\heatedTopics-V3
git status
```

If any leftover untracked files belong to this work, commit them with a descriptive message. Otherwise report "clean" and proceed.

---

## Self-Review Notes

- **Spec coverage:**
  - Three-stage fetch → Tasks 1–3 parsers + Task 4 caches + Task 5 pipeline orchestration.
  - Source ID `baidu` → Task 5 and Task 9.
  - Reporting title `"Baidu 热搜日报"` → Task 6.
  - Failure semantics (no exceptions, empty rows allowed) → Task 5 + the existing `_run_platform_pipeline` already handles empty matches.
  - `--offline` mode → Task 8.
  - Probe cleanup → Task 10.
  - Matrix + README updates → Task 9.
- **Placeholder scan:** No TODO / TBD in any step; each commit is concrete.
- **Type consistency:** `BaiduSearchArticle` defined in Task 2 reused in Task 5; `parse_baidu_article_response` defined in Task 3 reused in Task 5; cache helpers from Task 4 reused in Task 5.
- **Coverage gap spotted:** Task 5 `_details_for_items` is a no-op helper. The pipeline's `_run_platform_pipeline` already pairs `match.item` with `details_by_item_id[item.item_id]`. The pipeline builds `item_details` in stage 3 order and `_run_platform_pipeline` re-keys it by `item_id`, so behavior is correct. If a future refactor moves detail-fetching inside `_run_platform_pipeline`, drop the helper.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-19-baidu-hotword-source.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
