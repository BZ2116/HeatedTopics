# Sina / NetEase News v2 Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `sina-news` / `netease-news` to full parity with `toutiao --profile-v2` on three axes: `--custom-keyword`, daily quota hook, `hot_board_source` result field; also tighten `toutiao v2` to cap custom keywords at 5 (matching news-class).

**Architecture:** Three pipeline functions (`run_sina_news_pipeline`, `run_netease_news_pipeline`, `run_toutiao_pipeline_v2`) and two frozen dataclasses (`SinaNewsV2Result`, `NeteaseNewsV2Result`) gain additive parameters / fields. CLI handlers gain 4 new flags each. All defaults preserve backward compatibility (existing tests pass without changes outside the explicit update sites).

**Tech Stack:** Python 3.10+, pytest, dataclass(frozen=True), `state/quota/{user_id}.json` (existing quota.py module), `news_cache._single_flight` source labels.

**Spec:** `docs/superpowers/specs/2026-07-28-news-v2-parity-design.md`

---

## File Structure

**Modify:**
- `src/heated_topics_v3/pipeline.py` — three pipeline functions + two dataclasses
- `src/heated_topics_v3/cli.py` — `_add_news_args`, `_handle_sina_news`, `_handle_netease_news`
- `tests/test_sina_netease_v2_pipeline.py` — 10 new test cases
- `tests/test_toutiao_pipeline_v2.py` — 1 new test case
- `tests/test_cli.py` — 3 existing mock constructors updated to add `hot_board_source`

**No new files.**

---

## Task 1: sina-news pipeline — `custom_keywords` (TDD)

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py:1488-1497` (replace keywords construction)
- Test: `tests/test_sina_netease_v2_pipeline.py` (append new test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_sina_netease_v2_pipeline.py`:

```python
def test_sina_v2_custom_keywords_truncate_to_5(tmp_path: Path):
    """custom_keywords > 5 → fetcher sees only 5 search calls; extraction.source = 'custom'."""
    seen_keywords: list[str] = []
    profile = _sina_profile(tmp_path, core_keywords=("SHOULD_NOT_APPEAR",))

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url.startswith(SINA_SEARCH_URL):
            qs = parse_qs(urlparse(url).query)
            seen_keywords.append(qs.get("q", ["?"])[0])
            return SINA_SEARCH_RAW
        if url == SINA_HOT_URL:
            return SINA_HOT_RAW
        if "news.sina.com.cn" in url:
            return SINA_ARTICLE_HTML
        raise AssertionError(f"unexpected sina URL: {url}")

    result = run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
        custom_keywords=("A", "B", "C", "D", "E", "F", "G"),
    )
    assert len(seen_keywords) == 5, (
        f"sina v2 must cap custom_keywords at 5, fetcher saw {len(seen_keywords)}: {seen_keywords}"
    )
    assert seen_keywords == ["A", "B", "C", "D", "E"], (
        f"first 5 custom keywords in order, got {seen_keywords}"
    )
    assert "SHOULD_NOT_APPEAR" not in seen_keywords
    assert result.keyword_source == "custom"
    assert result.keyword_count == 5
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py::test_sina_v2_custom_keywords_truncate_to_5 -v
```

Expected: FAIL — `TypeError: run_sina_news_pipeline() got an unexpected keyword argument 'custom_keywords'` (or similar).

- [ ] **Step 3: Implement**

In `src/heated_topics_v3/pipeline.py`, add parameter to `run_sina_news_pipeline` signature (line 1413):

```python
def run_sina_news_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    top_n: int = 10,
    offline: bool = False,
    force_board_refresh: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
    custom_keywords: tuple[str, ...] = (),          # ← NEW
    on_search_committed: Callable[[], None] | None = None,  # ← NEW (used in Task 3)
    path_filters: PathFilters = PathFilters(
        hot_board_min=1000,
        article_heat_min=0,
        min_hot_board_before_search=3,
        include_is_toutiao_hot_fallback=False,
    ),
) -> "SinaNewsV2Result":
```

Replace the keywords construction block at lines 1488-1497:

```python
    if custom_keywords:
        keywords = tuple(k.strip() for k in custom_keywords if k.strip())[:5]
        extraction = PersonaKeywordExtraction(
            user_id=profile.profile_id,
            persona_signature="",
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
            source="custom",
        )
    else:
        keywords = [w for w in profile.core_keywords[:5] if w.strip()]
        extraction = PersonaKeywordExtraction(
            user_id=profile.profile_id,
            persona_signature="",
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
            source="core_keywords",
        )
    persona_keywords = tuple(keywords)
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py::test_sina_v2_custom_keywords_truncate_to_5 -v
```

Expected: PASS.

- [ ] **Step 5: Run full pipeline test file to confirm no regression**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py -q
```

Expected: All previous tests still pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sina_netease_v2_pipeline.py src/heated_topics_v3/pipeline.py
git commit -m "feat(sina-news): accept custom_keywords (capped at 5) in pipeline"
```

---

## Task 2: sina-news pipeline — `hot_board_source` field (TDD)

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py:1289-1300` (dataclass), `1607-1618` (result construction)
- Modify: `tests/test_cli.py:260-272`, `tests/test_cli.py:393-405` (mock constructors)
- Test: `tests/test_sina_netease_v2_pipeline.py` (append new test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_sina_netease_v2_pipeline.py`:

```python
_HOT_BOARD_SOURCE_LABELS = {"cache", "cache_after_wait", "fresh", "deadline_exceeded", "lock_timeout"}


def test_sina_v2_hot_board_source_in_result(tmp_path: Path):
    """Result.hot_board_source is one of the cache layer source labels."""
    profile = _sina_profile(tmp_path)
    result = run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_sina_fetcher(),
    )
    assert result.hot_board_source in _HOT_BOARD_SOURCE_LABELS, (
        f"hot_board_source must be one of {_HOT_BOARD_SOURCE_LABELS}, "
        f"got {result.hot_board_source!r}"
    )
    # First run against a fresh cache_root → either "fresh" or "cache_after_wait" (no prior data)
    assert result.hot_board_source == "fresh", (
        f"first run with no cache must return 'fresh', got {result.hot_board_source!r}"
    )
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py::test_sina_v2_hot_board_source_in_result -v
```

Expected: FAIL — `TypeError: __init__() missing 1 required positional argument: 'hot_board_source'` (or `AttributeError`).

- [ ] **Step 3: Add field to dataclass**

In `src/heated_topics_v3/pipeline.py`, modify `SinaNewsV2Result` (lines 1289-1300):

```python
@dataclass(frozen=True)
class SinaNewsV2Result:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str          # ← NEW
    keyword_source: str  # "core_keywords"
    keyword_count: int
    report_path: Path
    focused_path: Path
```

- [ ] **Step 4: Propagate `src` from board fetch to result construction**

In `run_sina_news_pipeline` (around lines 1467-1472), the `board_payload, src = _news_cache_get(...)` already captures `src`. We need to use `src` in the result construction.

Modify the return statement at lines 1607-1618:

```python
    return SinaNewsV2Result(
        user_id=profile.profile_id,
        date=run_result.date,
        run_dir=run_result.run_dir,
        top_n=top_n,
        candidates_total=run_result.candidates_total,
        kept_total=run_result.kept_total,
        paths=run_result.paths,
        hot_board_source=src,                  # ← NEW
        keyword_source=extraction.source,
        keyword_count=len(extraction.keywords),
        report_path=run_result.run_dir / "report.md",
        focused_path=run_result.run_dir / "focused.json",
    )
```

Verify `src` is still in scope at this point. If it has been shadowed by the search loop's `src`, you'll need to rename the board's `src` to `board_src` earlier in the function. Check the variable scope; if needed, edit the board fetch line (line 1467) to:

```python
    board_payload, board_src = _news_cache_get(
        get_or_fetch_sina_news_board_with_record,
        cache_root_path, today, live_board,
        offline=offline, force_refresh=force_board_refresh,
    )
    stats.record("board", board_src, forced=force_board_refresh)
```

…and update `board_text` extraction to use `board_payload` directly. Then pass `hot_board_source=board_src` in the return statement. (Only do this rename if the test still fails with `src` shadowed.)

- [ ] **Step 5: Update existing test_cli.py mocks**

In `tests/test_cli.py:260-272` and `tests/test_cli.py:393-405`, add `hot_board_source="fresh"` (or `"cache"`) to each `SinaNewsV2Result(...)` constructor. Example for line 260:

```python
        return SinaNewsV2Result(
            user_id="zhao_001",
            date="2026-07-25",
            run_dir=Path("outputs/users/zhao_001/2026-07-25/run_120000"),
            top_n=15,
            candidates_total=12,
            kept_total=7,
            paths={"A": 2, "B": 10},
            hot_board_source="fresh",     # ← NEW
            keyword_source="core_keywords",
            keyword_count=5,
            report_path=Path("outputs/users/zhao_001/2026-07-25/run_120000/report.md"),
            focused_path=Path("outputs/users/zhao_001/2026-07-25/run_120000/focused.json"),
        )
```

Apply the same one-line addition to the `SinaNewsV2Result(...)` at line 393-405. (The `NeteaseNewsV2Result` at line 345 is updated in Task 4.)

- [ ] **Step 6: Run new test, verify PASS**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py::test_sina_v2_hot_board_source_in_result -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite to confirm no regression**

```bash
uv run pytest -q
```

Expected: 356+ passed (356 from before + new tests; no failures).

- [ ] **Step 8: Commit**

```bash
git add src/heated_topics_v3/pipeline.py tests/test_sina_netease_v2_pipeline.py tests/test_cli.py
git commit -m "feat(sina-news): expose hot_board_source in result dataclass"
```

---

## Task 3: sina-news pipeline — `on_search_committed` quota hook (TDD)

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py` (add hook before return in `run_sina_news_pipeline`)
- Test: `tests/test_sina_netease_v2_pipeline.py` (append new test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_sina_netease_v2_pipeline.py`:

```python
def test_sina_v2_on_search_committed_fires_once(tmp_path: Path):
    """When custom_keywords provided, the on_search_committed callback fires exactly once."""
    counter = {"n": 0}
    profile = _sina_profile(tmp_path, core_keywords=("A", "B", "C"))

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url == SINA_HOT_URL:
            return SINA_HOT_RAW
        if url.startswith(SINA_SEARCH_URL):
            return SINA_SEARCH_RAW
        if "news.sina.com.cn" in url:
            return SINA_ARTICLE_HTML
        raise AssertionError(f"unexpected sina URL: {url}")

    run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
        custom_keywords=("A", "B", "C"),
        on_search_committed=lambda: counter.__setitem__("n", counter["n"] + 1),
    )
    assert counter["n"] == 1, (
        f"on_search_committed must fire exactly once per run, got {counter['n']}"
    )


def test_sina_v2_on_search_committed_not_fired_when_no_keywords(tmp_path: Path):
    """When core_keywords is empty AND custom_keywords is empty, hook must NOT fire."""
    counter = {"n": 0}
    profile = _sina_profile(tmp_path, core_keywords=())

    run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False,
        fetcher=_make_sina_fetcher(),
        on_search_committed=lambda: counter.__setitem__("n", counter["n"] + 1),
    )
    assert counter["n"] == 0, (
        f"on_search_committed must NOT fire when keywords is empty, got {counter['n']}"
    )
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py::test_sina_v2_on_search_committed_fires_once tests/test_sina_netease_v2_pipeline.py::test_sina_v2_on_search_committed_not_fired_when_no_keywords -v
```

Expected: FAIL — `TypeError: run_sina_news_pipeline() got an unexpected keyword argument 'on_search_committed'`.

- [ ] **Step 3: Implement**

The `on_search_committed` parameter was already added in Task 1 (Step 3). Now wire the hook.

Add to `run_sina_news_pipeline` just before the `return SinaNewsV2Result(...)` statement (around line 1605):

```python
    if on_search_committed is not None and persona_keywords:
        on_search_committed()
```

`persona_keywords` is already in scope from Task 1's refactor. The check `persona_keywords` non-empty is equivalent to "any search was attempted".

- [ ] **Step 4: Run new tests, verify PASS**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py::test_sina_v2_on_search_committed_fires_once tests/test_sina_netease_v2_pipeline.py::test_sina_v2_on_search_committed_not_fired_when_no_keywords -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -q
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/heated_topics_v3/pipeline.py tests/test_sina_netease_v2_pipeline.py
git commit -m "feat(sina-news): wire on_search_committed quota hook in pipeline"
```

---

## Task 4: netease-news pipeline — `custom_keywords` + `hot_board_source` + `on_search_committed` (TDD, mirror of Tasks 1-3)

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py:1622-1634` (dataclass), `1677-1721` (function signature + keywords block), `1825-1836` (return), `tests/test_cli.py:345-356` (mock)
- Test: `tests/test_sina_netease_v2_pipeline.py` (append 4 new tests)

This task mirrors Tasks 1, 2, 3 but for netease-news. Steps follow the same pattern.

- [ ] **Step 1: Write failing tests for all three features**

Append to `tests/test_sina_netease_v2_pipeline.py`:

```python
NETEASE_SEARCH_RAW = json.dumps({
    "code": 200, "message": "ok",
    "result": {"docs": [
        {"title": "AI 大爆发", "url": "https://www.163.com/dy/article/AI001.html", "docid": "AI001"},
    ]},
})

NETEASE_HOT_RAW = json.dumps({
    "code": 200, "data": [
        {"title": "AI 大爆发", "url": "https://www.163.com/dy/article/AI001.html", "hotValue": 9999,
         "category": "科技", "timestamp": "2026-07-25T10:00:00+08:00"},
    ],
})

NETEASE_ARTICLE_HTML = "<html><body><div class='post_body'><p>网易真实正文。</p></div></body></html>"


def _make_netease_fetcher():
    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url.startswith(NETEASE_SEARCH_URL):
            return NETEASE_SEARCH_RAW
        if url == NETEASE_HOT_URL:
            return NETEASE_HOT_RAW
        if "163.com" in url:
            return NETEASE_ARTICLE_HTML
        raise AssertionError(f"unexpected netease URL: {url}")
    return fetcher


def _netease_profile(tmp_path: Path, *, profile_id: str = "netease_v2_test",
                     core_keywords=("AI",)) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "profile_id": profile_id, "display_name": "v2 test",
        "domains": [], "audience": [], "content_modes": [],
        "preferred_platforms": ["netease_news"], "core_keywords": list(core_keywords),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_netease_v2_custom_keywords_truncate_to_5(tmp_path: Path):
    seen_keywords: list[str] = []
    profile = _netease_profile(tmp_path, core_keywords=("SHOULD_NOT_APPEAR",))

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url.startswith(NETEASE_SEARCH_URL):
            qs = parse_qs(urlparse(url).query)
            seen_keywords.append(qs.get("query", ["?"])[0])
            return NETEASE_SEARCH_RAW
        if url == NETEASE_HOT_URL:
            return NETEASE_HOT_RAW
        if "163.com" in url:
            return NETEASE_ARTICLE_HTML
        raise AssertionError(f"unexpected netease URL: {url}")

    result = run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
        custom_keywords=("A", "B", "C", "D", "E", "F", "G"),
    )
    assert len(seen_keywords) == 5
    assert seen_keywords == ["A", "B", "C", "D", "E"]
    assert result.keyword_source == "custom"
    assert result.keyword_count == 5


def test_netease_v2_hot_board_source_in_result(tmp_path: Path):
    profile = _netease_profile(tmp_path)
    result = run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_netease_fetcher(),
    )
    assert result.hot_board_source in _HOT_BOARD_SOURCE_LABELS
    assert result.hot_board_source == "fresh"


def test_netease_v2_on_search_committed_fires_once(tmp_path: Path):
    counter = {"n": 0}
    profile = _netease_profile(tmp_path)
    run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False,
        fetcher=_make_netease_fetcher(),
        custom_keywords=("A", "B"),
        on_search_committed=lambda: counter.__setitem__("n", counter["n"] + 1),
    )
    assert counter["n"] == 1
```

- [ ] **Step 2: Run new tests, verify FAIL**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py -k netease_v2 -v
```

Expected: FAIL — `TypeError: ... unexpected keyword argument`.

- [ ] **Step 3: Add parameters to `run_netease_news_pipeline` signature**

In `src/heated_topics_v3/pipeline.py`, modify the signature at line 1650 to add two params:

```python
def run_netease_news_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    top_n: int = 10,
    offline: bool = False,
    force_board_refresh: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
    custom_keywords: tuple[str, ...] = (),          # ← NEW
    on_search_committed: Callable[[], None] | None = None,  # ← NEW
    path_filters: PathFilters = PathFilters(
        hot_board_min=1000,
        article_heat_min=0,
        min_hot_board_before_search=3,
        include_is_toutiao_hot_fallback=False,
    ),
) -> "NeteaseNewsV2Result":
```

- [ ] **Step 4: Replace keywords construction (lines 1713-1721)**

```python
    if custom_keywords:
        keywords = tuple(k.strip() for k in custom_keywords if k.strip())[:5]
        extraction = PersonaKeywordExtraction(
            user_id=profile.profile_id,
            persona_signature="",
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
            source="custom",
        )
    else:
        keywords = [word for word in profile.core_keywords[:5] if word.strip()]
        extraction = PersonaKeywordExtraction(
            user_id=profile.profile_id,
            persona_signature="",
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
            source="core_keywords",
        )
    persona_keywords = tuple(keywords)
```

- [ ] **Step 5: Rename board `src` → `board_src` if shadowed**

Search for `board_payload, src = _news_cache_get` near line 1696. If the search loop later also defines `src` (line 1741), rename to `board_src` and update references. Same fallback logic as Task 2 Step 4.

- [ ] **Step 6: Add `hot_board_source` field to `NeteaseNewsV2Result`**

Modify the dataclass at lines 1622-1634:

```python
@dataclass(frozen=True)
class NeteaseNewsV2Result:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str          # ← NEW
    keyword_source: str  # "core_keywords"
    keyword_count: int
    report_path: Path
    focused_path: Path
```

- [ ] **Step 7: Update return statement (lines 1825-1836)**

```python
    return NeteaseNewsV2Result(
        user_id=profile.profile_id,
        date=run_result.date,
        run_dir=run_result.run_dir,
        top_n=top_n,
        candidates_total=run_result.candidates_total,
        kept_total=run_result.kept_total,
        paths=run_result.paths,
        hot_board_source=board_src,   # ← NEW (or src if not renamed)
        keyword_source=extraction.source,
        keyword_count=len(extraction.keywords),
        report_path=run_result.run_dir / "report.md",
        focused_path=run_result.run_dir / "focused.json",
    )
```

- [ ] **Step 8: Wire on_search_committed hook**

Add just before the return statement:

```python
    if on_search_committed is not None and persona_keywords:
        on_search_committed()
```

- [ ] **Step 9: Update existing test_cli.py mock at line 345**

Add `hot_board_source="fresh"` to the `NeteaseNewsV2Result(...)` constructor (mirror of Step 5 in Task 2).

- [ ] **Step 10: Run new tests, verify PASS**

```bash
uv run pytest tests/test_sina_netease_v2_pipeline.py -k netease_v2 -v
```

Expected: PASS.

- [ ] **Step 11: Run full suite**

```bash
uv run pytest -q
```

Expected: All pass.

- [ ] **Step 12: Commit**

```bash
git add src/heated_topics_v3/pipeline.py tests/test_sina_netease_v2_pipeline.py tests/test_cli.py
git commit -m "feat(netease-news): add custom_keywords, hot_board_source, on_search_committed"
```

---

## Task 5: toutiao v2 — `keyword_cap=5` (TDD)

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py:929-948` (signature), `970-986` (extraction branches)
- Test: `tests/test_toutiao_pipeline_v2.py` (append new test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_toutiao_pipeline_v2.py` (read existing file first to match import style; pattern should mirror `test_sina_netease_v2_pipeline.py`):

```python
def test_toutiao_v2_custom_keywords_cap_at_5(tmp_path: Path):
    """custom_keywords > 5 → fetcher sees at most 5 search calls."""
    seen_keywords: list[str] = []
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({
        "user_id": "toutiao_cap_test", "persona_signature": "x",
        "core_keywords": ["SHOULD_NOT_APPEAR"],
    }, ensure_ascii=False), encoding="utf-8")

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if "so.toutiao.com/search/" in url:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(url).query)
            seen_keywords.append(qs.get("keyword", ["?"])[0])
            return json.dumps({"keyword": "x", "count": 0, "dom": "<div></div>"})
        if "www.toutiao.com" in url:
            return "<html></html>"
        return ""

    from heated_topics_v3.pipeline import run_toutiao_pipeline_v2
    run_toutiao_pipeline_v2(
        profile_path=profile_path, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        fetcher=fetcher, top_n=10, custom_keywords=(
            "A", "B", "C", "D", "E", "F", "G",
        ),
    )
    assert len(seen_keywords) <= 5, (
        f"toutiao v2 custom_keywords must cap at 5, fetcher saw {len(seen_keywords)}: {seen_keywords}"
    )
    assert "SHOULD_NOT_APPEAR" not in seen_keywords
```

(If `run_toutiao_pipeline_v2` requires additional args in this repo, read the existing tests to find the minimum call shape; mirror exactly.)

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/test_toutiao_pipeline_v2.py::test_toutiao_v2_custom_keywords_cap_at_5 -v
```

Expected: FAIL — fetcher sees 7 keywords (current behavior is no cap), assert fails.

- [ ] **Step 3: Add `keyword_cap=5` parameter**

Modify the `run_toutiao_pipeline_v2` signature at line 929, adding the param after `custom_keywords`:

```python
def run_toutiao_pipeline_v2(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    hot_board_cache_root: Path = Path("cache"),
    persona_keyword_cache_root: Path = Path("cache/core_keywords"),
    force_hot_board_refresh: bool = False,
    allow_yesterday_fallback: bool = True,
    offline: bool = False,
    top_n: int = 10,
    path_filters: PathFilters = PathFilters(),
    fetcher: Callable[[str, int], str] | None = None,
    article_info_fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int], str] | None = None,
    rendered_text_fetcher: Callable[[str, int], str] | None = None,
    custom_keywords: tuple[str, ...] = (),
    keyword_cap: int = 5,                                  # ← NEW
    on_search_committed: Callable[[], None] | None = None,
    search_phase_budget_seconds: float = 20.0,
    _monotonic: Callable[[], float] = time.monotonic,
) -> "ToutiaoV2Result":
```

- [ ] **Step 4: Apply cap to `custom_keywords` branch (lines 970-977)**

```python
    if custom_keywords:
        capped = tuple(k.strip() for k in custom_keywords if k.strip())[:keyword_cap]
        extraction = PersonaKeywordExtraction(
            user_id=profile.user_id,
            persona_signature=profile.persona_signature,
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in capped),
            source="custom",
        )
```

- [ ] **Step 5: Apply cap to `core_keywords` branch (lines 978-986)**

```python
    else:
        capped = tuple(profile.core_keywords)[:keyword_cap]
        extraction = PersonaKeywordExtraction(
            user_id=profile.user_id,
            persona_signature=profile.persona_signature,
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in capped),
            source="core_keywords",
        )
```

(Note: `core_keywords` was previously uncapped; the cap is a tightening per the brainstorming decision. This applies to both branches uniformly.)

- [ ] **Step 6: Run new test, verify PASS**

```bash
uv run pytest tests/test_toutiao_pipeline_v2.py::test_toutiao_v2_custom_keywords_cap_at_5 -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest -q
```

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add src/heated_topics_v3/pipeline.py tests/test_toutiao_pipeline_v2.py
git commit -m "feat(toutiao-v2): cap custom_keywords at 5 (matches news-class)"
```

---

## Task 6: CLI — `_handle_sina_news` gains 4 flags + quota precheck + `hot_board_source` print

**Files:**
- Modify: `src/heated_topics_v3/cli.py:285-296` (`_add_news_args`), `362-389` (`_handle_sina_news`)

- [ ] **Step 1: Add 4 flags to `_add_news_args`**

In `src/heated_topics_v3/cli.py`, modify `_add_news_args` (line 285):

```python
def _add_news_args(parser: argparse.ArgumentParser) -> None:
    """Shared arg set for sina-news / netease-news (identical surface)."""
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--top-n", dest="top_n", default=10, type=int, help="Number of candidates to keep (default: 10)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force-board-refresh", dest="force_board_refresh", action="store_true")
    parser.add_argument("--force-search-refresh", dest="force_search_refresh", action="store_true")
    parser.add_argument("--force-article-refresh", dest="force_article_refresh", action="store_true")
    parser.add_argument("--matched-query-ids", dest="matched_query_ids", action="append", default=[])
    parser.add_argument("--custom-keyword", dest="custom_keyword", action="append", default=[])         # ← NEW
    parser.add_argument("--state-root", default=Path("state"), type=Path)                              # ← NEW
    parser.add_argument("--max-quota-per-day", dest="max_quota_per_day", default=3, type=int)          # ← NEW
    parser.add_argument("--skip-quota", dest="skip_quota", action="store_true")                         # ← NEW
```

- [ ] **Step 2: Modify `_handle_sina_news` (line 362)**

Read the existing function, then replace with:

```python
def _handle_sina_news(args) -> None:
    """Mirror of ``_handle_bilibili`` for the Sina News pipeline."""
    from heated_topics_v3.cli import _NEWS_QUOTA_IMPORT  # placeholder; real import below
    from heated_topics_v3.fetcher_factory import make_sina_news_fetcher
    from heated_topics_v3.pipeline import run_sina_news_pipeline
    from heated_topics_v3.quota import QuotaExceededError, check_quota, commit_quota, load_quota
    from heated_topics_v3.user_profile import load_user_profile
    from heated_topics_v3.utils_time import utc8_today

    fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    matched_query_ids = tuple(q.strip() for q in args.matched_query_ids if q.strip())
    custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())
    today = utc8_today()

    on_search_committed = None
    if not args.skip_quota:
        profile = load_user_profile(args.profile)
        user_id = getattr(profile, "profile_id", "") or ""
        if not user_id:
            print("profile 缺少 profile_id，无法应用配额；请用 --skip-quota", file=sys.stderr)
            raise SystemExit(2)
        state = load_quota(args.state_root, user_id, today)
        try:
            check_quota(state, args.max_quota_per_day)
        except QuotaExceededError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        on_search_committed = lambda: commit_quota(args.state_root, user_id, today)

    log_path = Path(__file__).resolve().parent.parent / ".sina_news_fetcher_log.json"
    fetcher = make_sina_news_fetcher(log_path=log_path, retry_policy=BaiduRetryPolicy())
    result = run_sina_news_pipeline(
        profile_path=args.profile,
        output_root=args.output_root,
        fetched_at=fetched_at,
        cache_root=args.cache_root,
        top_n=args.top_n,
        offline=args.offline,
        force_board_refresh=args.force_board_refresh,
        force_search_refresh=args.force_search_refresh,
        force_article_refresh=args.force_article_refresh,
        matched_query_ids=matched_query_ids,
        custom_keywords=custom_keywords,                    # ← NEW
        on_search_committed=on_search_committed,            # ← NEW
        fetcher=fetcher,
    )
    print(f"run_dir: {result.run_dir}")
    print(f"focused: {result.focused_path}")
    print(f"candidates: {result.kept_total}/{result.candidates_total}")
    print(f"paths: {result.paths}")
    print(f"hot_board_source: {result.hot_board_source}")  # ← NEW
    print(f"keyword_source: {result.keyword_source}")
    print(f"keyword_count: {result.keyword_count}")
```

**NOTE:** Verify the actual import paths in this repo before using them:
- `from heated_topics_v3.user_profile import load_user_profile` — may actually be `from heated_topics_v3.pipeline import load_user_profile`
- `from heated_topics_v3.utils_time import utc8_today` — may actually be `from heated_topics_v3.hot_board_cache import utc8_today` (per existing test_sina_netease_v2_pipeline.py line 17)
- `from heated_topics_v3.quota import ...` — confirm module path with `ls src/heated_topics_v3/quota.py`

Adjust imports to match the real repo. The control flow (load profile → get profile_id → check quota → set callback → run pipeline → print) is the contract.

- [ ] **Step 3: Verify CLI help shows new flags**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news --help
```

Expected: shows `--custom-keyword`, `--state-root`, `--max-quota-per-day`, `--skip-quota` in the help text.

- [ ] **Step 4: Smoke test with `--skip-quota` to bypass quota**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news --profile config/profiles/tech_ai_creator.json --offline --top-n 3 --skip-quota --output-root outputs/parity_check
```

Expected: prints `run_dir`, `focused`, `candidates`, `paths`, `hot_board_source`, `keyword_source`, `keyword_count` (7 lines).

- [ ] **Step 5: Smoke test with custom-keyword (offline)**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news --profile config/profiles/tech_ai_creator.json --offline --top-n 3 --skip-quota --output-root outputs/parity_check --custom-keyword AI --custom-keyword 芯片
```

Expected: `keyword_source: custom`, `keyword_count: 2`.

- [ ] **Step 6: Smoke test with quota enabled**

```bash
rm -rf state/quota 2>/dev/null
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news --profile config/profiles/tech_ai_creator.json --offline --top-n 3 --state-root state --max-quota-per-day 3 --output-root outputs/parity_check
```

Expected: runs successfully; `state/quota/tech_ai_creator.json` now exists with `{"date": "2026-07-28", "count": 1}` (or today's date).

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest -q
```

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add src/heated_topics_v3/cli.py
git commit -m "feat(cli): sina-news gains custom-keyword + quota flags + hot_board_source print"
```

---

## Task 7: CLI — `_handle_netease_news` (mirror of Task 6)

**Files:**
- Modify: `src/heated_topics_v3/cli.py:392-...` (`_handle_netease_news`)

- [ ] **Step 1: Mirror Task 6 changes for `_handle_netease_news`**

Apply the same changes to `_handle_netease_news` as to `_handle_sina_news` in Task 6:
- Add `custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())`
- Add the quota precheck block (load profile, get profile_id, check_quota, set callback)
- Pass `custom_keywords` and `on_search_committed` to `run_netease_news_pipeline`
- Print `hot_board_source: {result.hot_board_source}` in the print block

Replace the function body entirely (mirror Task 6 Step 2 with `run_netease_news_pipeline` instead of `run_sina_news_pipeline`, and `.netease_news_fetcher_log.json` log path).

- [ ] **Step 2: Verify CLI help**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" netease-news --help
```

Expected: shows the same 4 new flags as sina-news.

- [ ] **Step 3: Smoke test with `--skip-quota`**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" netease-news --profile config/profiles/tech_ai_creator.json --offline --top-n 3 --skip-quota --output-root outputs/parity_check
```

Expected: 7-line print block including `hot_board_source`.

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest -q
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/heated_topics_v3/cli.py
git commit -m "feat(cli): netease-news gains custom-keyword + quota flags + hot_board_source print"
```

---

## Task 8: End-to-end live fetch verification (real Path B)

- [ ] **Step 1: Run sina-news with custom-keyword + quota enabled**

```bash
rm -rf state/quota/tech_ai_creator.json
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news \
    --profile config/profiles/tech_ai_creator.json \
    --top-n 3 \
    --state-root state --max-quota-per-day 3 \
    --custom-keyword AI --custom-keyword 芯片 --custom-keyword 大模型 --custom-keyword 算力 \
    --output-root outputs/parity_live
```

Expected: `keyword_source: custom`, `keyword_count: 4`, `candidates: 3/15`, `hot_board_source: fresh` (or `cache_after_wait`).

- [ ] **Step 2: Verify quota state file**

```bash
cat state/quota/tech_ai_creator.json
```

Expected: `{"schema_version": 1, "date": "2026-07-28", "user_id": "tech_ai_creator", "count": 1, "limit": 3}` (or similar — schema may vary).

- [ ] **Step 3: Run netease-news with custom-keyword + quota enabled**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" netease-news \
    --profile config/profiles/tech_ai_creator.json \
    --top-n 3 \
    --state-root state --max-quota-per-day 3 \
    --custom-keyword AI --custom-keyword 芯片 \
    --output-root outputs/parity_live
```

Expected: similar output, `count` becomes 2 in quota state.

- [ ] **Step 4: Verify quota increments**

```bash
cat state/quota/tech_ai_creator.json
```

Expected: `count: 2`.

- [ ] **Step 5: Trigger quota exceeded**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" netease-news \
    --profile config/profiles/tech_ai_creator.json \
    --top-n 3 --offline \
    --state-root state --max-quota-per-day 3 \
    --output-root outputs/parity_live
```

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news \
    --profile config/profiles/tech_ai_creator.json \
    --top-n 3 --offline \
    --state-root state --max-quota-per-day 3 \
    --output-root outputs/parity_live
```

Expected: third call (count=3 → would-be count=4) exits with code 2 and prints quota error to stderr.

- [ ] **Step 6: Verify `--skip-quota` bypasses**

```bash
uv run python -c "from heated_topics_v3.cli import main; main()" sina-news \
    --profile config/profiles/tech_ai_creator.json \
    --top-n 3 --offline --skip-quota \
    --output-root outputs/parity_live
```

Expected: runs normally despite quota being exhausted.

- [ ] **Step 7: Clean up parity test artifacts (optional)**

```bash
rm -rf state/quota outputs/parity_check outputs/parity_live outputs/online_check
```

- [ ] **Step 8: Commit any final tweaks**

If during smoke tests you discovered any small fixes (typos in print order, missing imports, etc.), commit them now. If no changes, skip this step.

```bash
git status
# (commit only if there are changes)
```

---

## Self-Review Notes

**Spec coverage map:**

| Spec requirement | Task |
|---|---|
| sina-news: `custom_keywords` parameter | Task 1 |
| sina-news: cap at 5 | Task 1 |
| sina-news: `hot_board_source` field | Task 2 |
| sina-news: `on_search_committed` hook | Task 3 |
| netease-news: `custom_keywords` + cap | Task 4 |
| netease-news: `hot_board_source` | Task 4 |
| netease-news: `on_search_committed` | Task 4 |
| toutiao v2: `keyword_cap=5` | Task 5 |
| CLI sina-news: 4 flags + quota + print | Task 6 |
| CLI netease-news: 4 flags + quota + print | Task 7 |
| Live Path B verification | Task 8 |

All 11 spec items covered by 8 tasks.

**Risks addressed:**
- `src` variable shadowing in pipeline: Tasks 2 & 4 include explicit rename-to-`board_src` instructions if needed
- `tests/test_cli.py` mocks need `hot_board_source`: Tasks 2 (line 260, 393) & 4 (line 345) call this out
- `profile.profile_id` empty-string case: Task 6 explicit `SystemExit(2)` branch

**Ordering rationale:** Tasks 1-5 are pure pipeline changes (testable in isolation). Tasks 6-7 are CLI changes that depend on 1-5 already landing. Task 8 is end-to-end verification.