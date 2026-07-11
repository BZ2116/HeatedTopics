# Toutiao Keyword Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Toutiao collection query-driven by searching profile keywords, parsing search results, and merging them with the global hot board.

**Architecture:** Keep `providers/toutiao.py` as the platform adapter. Add deterministic query expansion and search-result parsing there, then update `pipeline.py` so Toutiao writes `hot_board_items.json`, `search_results.json`, merged `hot_items.json`, matches, details, and report in the existing output structure.

**Tech Stack:** Python 3.14, standard library `urllib`, `json`, `html.parser`, existing dataclasses in `contracts.py`, existing pytest test suite.

## Global Constraints

- Do not use an LLM for query expansion in this version.
- Keep browser/session detail extraction out of scope.
- Preserve `outputs/{profile_id}/toutiao/run_{YYYYMMDD_HHMMSS}/`.
- Keep the global Toutiao hot board as supplemental data, not the primary source.
- Use TDD: write failing tests before production code.
- Do not commit generated `outputs/`.
- Do not include unrelated `.gitignore` local changes.

---

### Task 1: Toutiao Query Expansion

**Files:**
- Modify: `src/heated_topics_v3/providers/toutiao.py`
- Test: `tests/providers/test_toutiao.py`

**Interfaces:**
- Consumes: `TopicQuery` from `heated_topics_v3.contracts`.
- Produces: `build_toutiao_search_phrases(queries: tuple[TopicQuery, ...]) -> tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/providers/test_toutiao.py`:

```python
def test_build_toutiao_search_phrases_expands_profile_queries():
    queries = (
        TopicQuery(
            query_id="tech_ai_creator_q_001_core_hot",
            profile_id="tech_ai_creator",
            query="AI Agent MCP",
            intent="profile_core_hot",
            target_platforms=("toutiao",),
            keywords=("AI Agent", "MCP"),
            usage="filter_and_enrich_hot_lists",
            priority=100,
        ),
        TopicQuery(
            query_id="tech_ai_creator_q_002_entity_hot",
            profile_id="tech_ai_creator",
            query="Claude Code",
            intent="profile_entity_hot",
            target_platforms=("toutiao",),
            keywords=("Claude Code",),
            usage="filter_and_enrich_hot_lists",
            priority=80,
        ),
    )

    phrases = build_toutiao_search_phrases(queries)

    assert phrases == (
        "AI Agent MCP",
        "AI Agent",
        "AI智能体",
        "MCP",
        "MCP 协议",
        "Claude Code",
        "Claude Code AI编程",
    )
```

Also add imports:

```python
from heated_topics_v3.contracts import TopicQuery
from heated_topics_v3.providers.toutiao import build_toutiao_search_phrases
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\providers\test_toutiao.py::test_build_toutiao_search_phrases_expands_profile_queries -q
```

Expected: FAIL because `build_toutiao_search_phrases` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add to `src/heated_topics_v3/providers/toutiao.py`:

```python
from heated_topics_v3.contracts import TopicQuery

TOUTIAO_QUERY_ALIASES = {
    "AI Agent": ("AI智能体",),
    "Claude Code": ("Claude Code AI编程",),
    "MCP": ("MCP 协议",),
    "Cursor": ("Cursor AI编程",),
}


def build_toutiao_search_phrases(queries: tuple[TopicQuery, ...]) -> tuple[str, ...]:
    phrases: list[str] = []
    for query in queries:
        _append_unique(phrases, query.query)
        for keyword in query.keywords:
            _append_unique(phrases, keyword)
            for alias in TOUTIAO_QUERY_ALIASES.get(keyword, ()):
                _append_unique(phrases, alias)
    return tuple(phrases)


def _append_unique(values: list[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in values:
        values.append(normalized)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\providers\test_toutiao.py::test_build_toutiao_search_phrases_expands_profile_queries -q
```

Expected: PASS.

---

### Task 2: Toutiao Search Fetching And Parsing

**Files:**
- Modify: `src/heated_topics_v3/providers/toutiao.py`
- Test: `tests/providers/test_toutiao.py`

**Interfaces:**
- Produces: `TOUTIAO_SEARCH_URL`.
- Produces: `fetch_toutiao_search_items(phrases: tuple[str, ...], fetched_at: str, fetcher=None, timeout_seconds: int = 20) -> list[HotItem]`.
- Produces: `parse_toutiao_search_response(response_text: str, phrase: str, fetched_at: str) -> list[HotItem]`.

- [ ] **Step 1: Write failing parser and fetcher tests**

Add tests:

```python
def test_parse_toutiao_search_response_maps_dom_results_to_hot_items():
    payload = {
        "keyword": "AI智能体",
        "count": 2,
        "dom": '''
        <div class="result-card">
          <a href="https://www.toutiao.com/article/1">AI智能体创业公司融资</a>
          <div>阅读 12万 评论 345</div>
          <p>AI智能体正在进入企业工作流。</p>
        </div>
        <div class="result-card">
          <a href="https://www.toutiao.com/article/2">AI智能体产品盘点</a>
          <div>热度 8866</div>
          <p>多款AI产品更新。</p>
        </div>
        ''',
    }

    items = parse_toutiao_search_response(
        json.dumps(payload),
        phrase="AI智能体",
        fetched_at="2026-07-11T15:20:00+08:00",
    )

    assert [item.item_id for item in items] == ["toutiao_search_1", "toutiao_search_2"]
    assert items[0].title == "AI智能体创业公司融资"
    assert items[0].heat.metric_name == "search_engagement"
    assert items[0].heat.metrics["reads"] == 120000
    assert items[0].heat.metrics["comments"] == 345
    assert items[0].raw_payload["search_phrase"] == "AI智能体"
    assert items[1].heat.value == 8866
    assert items[1].heat.metric_name == "search_heat"


def test_fetch_toutiao_search_items_calls_search_endpoint_for_each_phrase():
    calls = []

    def fake_fetcher(url: str, timeout_seconds: int) -> str:
        calls.append(url)
        return json.dumps({"keyword": "AI智能体", "count": 0, "dom": ""})

    items = fetch_toutiao_search_items(
        phrases=("AI智能体", "MCP 协议"),
        fetched_at="2026-07-11T15:20:00+08:00",
        fetcher=fake_fetcher,
    )

    assert items == []
    assert "keyword=AI" in calls[0]
    assert "keyword=MCP" in calls[1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\providers\test_toutiao.py::test_parse_toutiao_search_response_maps_dom_results_to_hot_items tests\providers\test_toutiao.py::test_fetch_toutiao_search_items_calls_search_endpoint_for_each_phrase -q
```

Expected: FAIL because functions do not exist.

- [ ] **Step 3: Implement parsing and fetching**

Add an HTML parser that extracts `<a href>` title/link cards and local text, plus helpers to parse Chinese numeric units:

```python
from urllib.parse import urlencode

TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"


def fetch_toutiao_search_items(
    phrases: tuple[str, ...],
    fetched_at: str,
    fetcher=None,
    timeout_seconds: int = 20,
) -> list[HotItem]:
    fetch = fetcher or _fetch_text
    items: list[HotItem] = []
    for phrase in phrases:
        url = f"{TOUTIAO_SEARCH_URL}?{urlencode({'keyword': phrase, 'pd': 'information', 'source': 'search_subtab_switch', 'from': 'information', 'format': 'json', 'count': '10', 'offset': '0'})}"
        items.extend(parse_toutiao_search_response(fetch(url, timeout_seconds), phrase, fetched_at))
    return items
```

Use `item_id = "toutiao_search_{article_id_or_rank}"`, `platform = "toutiao"`, `item_type = "search_result"`, `category = "search"`, and set `raw_payload["source_kind"] = "search_result"`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\providers\test_toutiao.py -q
```

Expected: PASS.

---

### Task 3: Merge Search Results With Hot Board And Pipeline Outputs

**Files:**
- Modify: `src/heated_topics_v3/providers/toutiao.py`
- Modify: `src/heated_topics_v3/pipeline.py`
- Test: `tests/providers/test_toutiao.py`
- Test: `tests/test_toutiao_pipeline.py`

**Interfaces:**
- Produces: `merge_toutiao_items(search_items: list[HotItem], hot_board_items: list[HotItem]) -> list[HotItem]`.
- Updates: `run_toutiao_pipeline(...)` writes `hot_board_items` and `search_results` paths.

- [ ] **Step 1: Write failing merge test**

Add:

```python
def test_merge_toutiao_items_uses_hot_board_heat_for_overlapping_urls():
    search_items = parse_toutiao_search_response(
        json.dumps({
            "keyword": "AI智能体",
            "count": 1,
            "dom": '<a href="https://www.toutiao.com/article/1">AI智能体创业公司融资</a>',
        }),
        phrase="AI智能体",
        fetched_at="2026-07-11T15:20:00+08:00",
    )
    hot_board_items = parse_toutiao_hot_board_response(
        json.dumps({
            "data": [{
                "ClusterId": "1",
                "Title": "AI智能体创业公司融资",
                "Url": "https://www.toutiao.com/article/1",
                "HotValue": "9000",
                "QueryWord": "AI智能体创业公司融资",
            }]
        }),
        fetched_at="2026-07-11T15:20:00+08:00",
    )

    merged = merge_toutiao_items(search_items, hot_board_items)

    assert len(merged) == 1
    assert merged[0].heat.value == 9000
    assert merged[0].heat.metric_name == "hot_value"
    assert merged[0].raw_payload["source_kind"] == "search_hot_board_overlap"
```

- [ ] **Step 2: Update pipeline test expectation**

In `tests/test_toutiao_pipeline.py`, update the fake fetcher so it returns hot board JSON for the hot board URL and search JSON for search URLs. Assert outputs include:

```python
assert set(outputs) == {
    "profile",
    "queries",
    "hot_board_items",
    "search_results",
    "hot_items",
    "matches",
    "item_details",
    "report",
}
assert outputs["hot_board_items"].name == "hot_board_items.json"
assert outputs["search_results"].name == "search_results.json"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\providers\test_toutiao.py::test_merge_toutiao_items_uses_hot_board_heat_for_overlapping_urls tests\test_toutiao_pipeline.py -q
```

Expected: FAIL because merge and extra outputs do not exist.

- [ ] **Step 4: Implement merge and pipeline outputs**

In `providers/toutiao.py`, add `merge_toutiao_items`.

In `pipeline.py`, change `run_toutiao_pipeline` to:

1. Load profile and queries.
2. Build search phrases.
3. Fetch hot board items.
4. Fetch search results.
5. Merge into final hot items.
6. Match final hot items.
7. Write `hot_board_items.json`, `search_results.json`, `hot_items.json`, `matches.json`, `item_details.json`, and `report.md`.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\providers\test_toutiao.py tests\test_toutiao_pipeline.py -q
```

Expected: PASS.

---

### Task 4: Report And Documentation Update

**Files:**
- Modify: `src/heated_topics_v3/reporting.py`
- Modify: `docs/specs/toutiao-implementation-report.md`
- Test: `tests/test_toutiao_pipeline.py`

**Interfaces:**
- Updates report detail status lines to include weak heat signal when `raw_payload["heat_signal_strength"] == "weak"`.

- [ ] **Step 1: Write failing report assertion**

In `tests/test_toutiao_pipeline.py`, assert:

```python
assert "search_result" in report
assert "weak" in report or "hot_value" in report
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests\test_toutiao_pipeline.py -q
```

Expected: FAIL if report does not include search source and heat signal wording.

- [ ] **Step 3: Implement report wording and docs**

Update `reporting.py` to add a line per match:

```python
f"- Source: {item.raw_payload.get('source_kind', item.platform)}",
f"- Heat signal: {item.raw_payload.get('heat_signal_strength', item.heat.metric_name)}",
```

Update `docs/specs/toutiao-implementation-report.md` with the keyword-search flow, search endpoint, and current limitations.

- [ ] **Step 4: Run full verification**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest -q
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli toutiao --profile config\profiles\tech_ai_creator.json --output-root outputs
```

Expected:

- `pytest`: all tests pass.
- CLI writes `hot_board_items.json`, `search_results.json`, `hot_items.json`, `matches.json`, `item_details.json`, and `report.md`.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/heated_topics_v3/providers/toutiao.py src/heated_topics_v3/pipeline.py src/heated_topics_v3/reporting.py tests/providers/test_toutiao.py tests/test_toutiao_pipeline.py docs/specs/toutiao-implementation-report.md
git commit -m "feat: drive Toutiao collection from profile search"
```

