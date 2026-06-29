# Profile-driven Search Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `search_discovery` from category-based multi-query search into profile-driven dynamic routing where each enabled search source receives one profile-specific query per request.

**Architecture:** Add a focused routing module that classifies user intent, computes source weights, and emits one `SearchRoute` per source. Keep existing provider, normalization, enrichment, clustering, and isolated output paths, but change the CLI orchestration to execute routes instead of nested category/query loops.

**Tech Stack:** Python 3.13/3.14 compatible code, dataclasses, existing `uv run pytest`, existing provider classes under `src/search_discovery`.

---

## File Structure

- Modify `src/search_discovery/types.py`
  - Add `SearchRoute`.
  - Extend `CreatorProfile` with optional `platforms`, `content_goal`, and `exclude_keywords` while preserving old profile compatibility.
  - Extend `SearchResult` with `route_weight`, `route_reason`, and `matched_keywords`.

- Create `src/search_discovery/routing.py`
  - Own dynamic intent classification, source weight calculation, keyword compaction, and per-source query generation.
  - Public API: `build_search_routes(profile: CreatorProfile) -> list[SearchRoute]`.

- Modify `src/search_discovery/providers.py`
  - Preserve existing normalization behavior.
  - Copy route metadata from provider rows into `SearchResult`.

- Modify `src/search_discovery/cli.py`
  - Replace `classify_keywords -> generate_query_bundles -> plan_sources_for_category` nested loops with `build_search_routes`.
  - Ensure each source is searched at most once per request.
  - Keep output paths under `data/search_discovery` and `reports/search_discovery`.

- Modify `src/search_discovery/discovery.py`
  - Use `route_weight` when present so dynamic weights affect topic scoring and source hits.
  - Preserve fallback to `profile_source_weights` for old rows.

- Modify `src/search_discovery/render.py`
  - Render creator-facing report fields: match reason, key info, creation angles, evidence URLs, confidence, risk.
  - Keep it template-based when no LLM integration exists.

- Tests:
  - Create `tests/search_discovery/test_routing.py`.
  - Modify `tests/search_discovery/test_cli.py`.
  - Modify `tests/search_discovery/test_providers.py`.
  - Modify `tests/search_discovery/test_render.py`.

## Task 1: Extend Types For Routing Metadata

**Files:**
- Modify: `src/search_discovery/types.py`
- Test: `tests/search_discovery/test_types.py`

- [ ] **Step 1: Write failing tests**

Add these tests to `tests/search_discovery/test_types.py`:

```python
from src.search_discovery.types import CreatorProfile, SearchResult, SearchRoute


def test_creator_profile_accepts_new_request_fields():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "platforms": ["小红书", "公众号"],
            "track_tags": ["AI", "开源项目"],
            "custom_keywords": ["AI Agent", "MCP", "RAG"],
            "content_goal": "寻找近期技术趋势",
            "exclude_keywords": ["纯营销"],
        }
    )

    assert profile.platforms == ["小红书", "公众号"]
    assert profile.content_goal == "寻找近期技术趋势"
    assert profile.exclude_keywords == ["纯营销"]
    assert profile.all_keywords() == ["AI", "开源项目", "AI Agent", "MCP", "RAG"]


def test_search_route_serializes_profile_specific_query():
    route = SearchRoute(
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
        intent="tech_project",
        weight=100,
        reason="科技类创作者关注开源项目，GitHub 适合召回 repo。",
    )

    assert route.to_dict()["source_id"] == "github_search"
    assert route.to_dict()["query"].startswith("AI Agent MCP RAG")
    assert route.to_dict()["weight"] == 100


def test_search_result_keeps_route_metadata():
    result = SearchResult(
        result_id="r1",
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
        keyword_category="tech_project",
        title="example/agent-framework",
        url="https://github.com/example/agent-framework",
        snippet="Agent framework",
        route_weight=100,
        route_reason="GitHub is preferred for tech project discovery.",
        matched_keywords=["AI Agent"],
    )

    row = result.to_dict()
    assert row["route_weight"] == 100
    assert row["route_reason"] == "GitHub is preferred for tech project discovery."
    assert row["matched_keywords"] == ["AI Agent"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_types.py -q
```

Expected: FAIL because `SearchRoute`, `platforms`, `content_goal`, `exclude_keywords`, `route_weight`, `route_reason`, and `matched_keywords` do not exist yet.

- [ ] **Step 3: Implement minimal type changes**

Update `src/search_discovery/types.py`:

```python
@dataclass(frozen=True)
class CreatorProfile:
    creator_id: str
    role: str
    profile_type: str
    track_tags: list[str] = field(default_factory=list)
    custom_keywords: list[str] = field(default_factory=list)
    content_modes: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    content_goal: str = ""
    exclude_keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "CreatorProfile":
        return cls(
            creator_id=str(row.get("creator_id", row.get("user_id", ""))),
            role=str(row.get("role", "")),
            profile_type=str(row.get("profile_type", "")),
            track_tags=[str(item) for item in row.get("track_tags", [])],
            custom_keywords=[str(item) for item in row.get("custom_keywords", row.get("keywords", []))],
            content_modes=[str(item) for item in row.get("content_modes", [])],
            platforms=[str(item) for item in row.get("platforms", row.get("platform", []))],
            content_goal=str(row.get("content_goal", "")),
            exclude_keywords=[str(item) for item in row.get("exclude_keywords", [])],
        )
```

Add after `PlannedSource`:

```python
@dataclass(frozen=True)
class SearchRoute:
    source_id: str
    source_role: str
    query: str
    intent: str
    weight: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Extend `SearchResult` fields:

```python
    route_weight: int = 0
    route_reason: str = ""
    matched_keywords: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_types.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/types.py tests/search_discovery/test_types.py
git commit -m "feat: add search route metadata types"
```

## Task 2: Add Dynamic Source Router

**Files:**
- Create: `src/search_discovery/routing.py`
- Test: `tests/search_discovery/test_routing.py`

- [ ] **Step 1: Write failing router tests**

Create `tests/search_discovery/test_routing.py`:

```python
from src.search_discovery.routing import build_search_routes, compact_query_keywords, classify_search_intent
from src.search_discovery.types import CreatorProfile


def _tech_profile() -> CreatorProfile:
    return CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "track_tags": ["AI", "开发者工具", "开源项目"],
            "custom_keywords": ["AI Agent", "MCP", "RAG"],
            "content_goal": "寻找近期适合内容创作的技术趋势和项目",
        }
    )


def test_compact_query_keywords_prioritizes_custom_keywords():
    assert compact_query_keywords(_tech_profile()) == "AI Agent MCP RAG"


def test_classify_search_intent_detects_tech_project():
    assert classify_search_intent(_tech_profile()) == "tech_project"


def test_build_search_routes_returns_one_route_per_source():
    routes = build_search_routes(_tech_profile())

    source_ids = [route.source_id for route in routes]
    assert len(source_ids) == len(set(source_ids))
    assert source_ids[:2] == ["github_search", "juejin_content"]
    assert all(route.query for route in routes)


def test_build_search_routes_uses_source_specific_queries():
    routes = {route.source_id: route for route in build_search_routes(_tech_profile())}

    assert routes["github_search"].query == (
        "AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01"
    )
    assert routes["juejin_content"].query == "AI Agent MCP RAG 教程 实践 案例 开发者"
    assert routes["baidu_qianfan_search"].query == "AI Agent MCP RAG 最新进展 行业动态 应用"
    assert routes["news_api_cn"].query == "AI Agent MCP RAG 最新 发布 融资 应用"
    assert routes["github_search"].weight > routes["news_api_cn"].weight


def test_business_profile_routes_news_above_github():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_002",
            "role": "商业创业博主",
            "profile_type": "business_startup_creator",
            "track_tags": ["SaaS", "融资", "AI 应用"],
            "custom_keywords": ["AI Agent 商业化"],
            "content_goal": "寻找行业新闻和商业趋势",
        }
    )

    routes = build_search_routes(profile)
    source_ids = [route.source_id for route in routes]
    assert source_ids[0] == "news_api_cn"
    assert source_ids.index("baidu_qianfan_search") < source_ids.index("github_search")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_routing.py -q
```

Expected: FAIL because `src.search_discovery.routing` does not exist.

- [ ] **Step 3: Implement router**

Create `src/search_discovery/routing.py`:

```python
from src.search_discovery.config import source_registry
from src.search_discovery.types import CreatorProfile, SearchRoute


PROFILE_BASE_WEIGHTS = {
    "tech_ai_creator": {
        "github_search": 95,
        "juejin_content": 90,
        "baidu_qianfan_search": 80,
        "news_api_cn": 65,
    },
    "developer_creator": {
        "github_search": 100,
        "juejin_content": 95,
        "baidu_qianfan_search": 70,
        "news_api_cn": 45,
    },
    "business_startup_creator": {
        "github_search": 35,
        "juejin_content": 35,
        "baidu_qianfan_search": 85,
        "news_api_cn": 90,
    },
    "general_hot_topic_creator": {
        "github_search": 5,
        "juejin_content": 10,
        "baidu_qianfan_search": 95,
        "news_api_cn": 90,
    },
}

INTENT_BOOSTS = {
    "tech_project": {
        "github_search": 20,
        "juejin_content": 10,
        "baidu_qianfan_search": -10,
        "news_api_cn": -20,
    },
    "tech_article": {
        "github_search": 5,
        "juejin_content": 20,
        "baidu_qianfan_search": 5,
        "news_api_cn": -10,
    },
    "news_trend": {
        "github_search": -20,
        "juejin_content": -10,
        "baidu_qianfan_search": 15,
        "news_api_cn": 20,
    },
    "product_trend": {
        "github_search": -10,
        "juejin_content": 0,
        "baidu_qianfan_search": 15,
        "news_api_cn": 10,
    },
    "content_angle": {
        "github_search": -5,
        "juejin_content": 5,
        "baidu_qianfan_search": 15,
        "news_api_cn": 10,
    },
}

SOURCE_QUERY_TEMPLATES = {
    "github_search": "{keywords} in:name,description stars:>50 pushed:>2025-01-01",
    "juejin_content": "{keywords} 教程 实践 案例 开发者",
    "baidu_qianfan_search": "{keywords} 最新进展 行业动态 应用",
    "news_api_cn": "{keywords} 最新 发布 融资 应用",
}


def build_search_routes(profile: CreatorProfile) -> list[SearchRoute]:
    intent = classify_search_intent(profile)
    keywords = compact_query_keywords(profile)
    sources = source_registry()
    base_weights = PROFILE_BASE_WEIGHTS.get(profile.profile_type, PROFILE_BASE_WEIGHTS["general_hot_topic_creator"])
    boosts = INTENT_BOOSTS.get(intent, INTENT_BOOSTS["content_angle"])

    routes: list[SearchRoute] = []
    for source_id, template in SOURCE_QUERY_TEMPLATES.items():
        weight = max(0, min(100, base_weights.get(source_id, 0) + boosts.get(source_id, 0)))
        if weight <= 0:
            continue
        source = sources[source_id]
        routes.append(
            SearchRoute(
                source_id=source_id,
                source_role=source.source_role,
                query=template.format(keywords=keywords),
                intent=intent,
                weight=weight,
                reason=_route_reason(profile, source_id, intent),
            )
        )
    return sorted(routes, key=lambda route: route.weight, reverse=True)


def classify_search_intent(profile: CreatorProfile) -> str:
    text = " ".join(
        [
            profile.role,
            profile.profile_type,
            profile.content_goal,
            *profile.track_tags,
            *profile.custom_keywords,
            *profile.content_modes,
        ]
    ).lower()
    if any(term in text for term in ["github", "开源", "repo", "框架", "sdk", "开发者工具", "agent", "mcp", "rag"]):
        return "tech_project"
    if any(term in text for term in ["教程", "实践", "案例", "源码", "部署", "架构"]):
        return "tech_article"
    if any(term in text for term in ["新闻", "最新", "发布", "融资", "政策", "行业"]):
        return "news_trend"
    if any(term in text for term in ["产品", "应用", "商业化", "saas", "工具"]):
        return "product_trend"
    return "content_angle"


def compact_query_keywords(profile: CreatorProfile, limit: int = 5) -> str:
    candidates = profile.custom_keywords or profile.track_tags
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        result.append(cleaned)
        if len(result) >= limit:
            break
    return " ".join(result)


def _route_reason(profile: CreatorProfile, source_id: str, intent: str) -> str:
    source_labels = {
        "github_search": "GitHub 适合召回开源项目、repo、框架和开发者工具。",
        "juejin_content": "技术内容源适合召回中文教程、实践案例和开发者文章。",
        "baidu_qianfan_search": "通用搜索适合召回中文网页、博客、问答和行业资料。",
        "news_api_cn": "新闻搜索适合召回时效新闻、发布信息和事实背景。",
    }
    return f"{profile.role or profile.profile_type} 的当前搜索意图是 {intent}，{source_labels[source_id]}"
```

- [ ] **Step 4: Run router tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_routing.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/routing.py tests/search_discovery/test_routing.py
git commit -m "feat: add profile driven search router"
```

## Task 3: Preserve Route Metadata During Normalization

**Files:**
- Modify: `src/search_discovery/providers.py`
- Test: `tests/search_discovery/test_providers.py`

- [ ] **Step 1: Write failing normalization test**

Add to `tests/search_discovery/test_providers.py`:

```python
from src.search_discovery.providers import normalize_provider_rows


def test_normalize_provider_rows_keeps_route_metadata():
    results = normalize_provider_rows(
        rows=[
            {
                "result_id": "r1",
                "title": "example/agent-framework",
                "url": "https://github.com/example/agent-framework",
                "snippet": "Agent framework",
                "route_weight": 100,
                "route_reason": "GitHub route reason",
                "matched_keywords": ["AI Agent"],
            }
        ],
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
        keyword_category="tech_project",
        fetched_at="2026-06-29T12:00:00+08:00",
    )

    assert results[0].route_weight == 100
    assert results[0].route_reason == "GitHub route reason"
    assert results[0].matched_keywords == ["AI Agent"]
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_providers.py::test_normalize_provider_rows_keeps_route_metadata -q
```

Expected: FAIL because route metadata is ignored.

- [ ] **Step 3: Implement metadata passthrough**

In `src/search_discovery/providers.py`, add these fields when constructing `SearchResult`:

```python
            route_weight=int(row.get("route_weight", 0) or 0),
            route_reason=str(row.get("route_reason", "")),
            matched_keywords=[str(item) for item in row.get("matched_keywords", [])],
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_providers.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/providers.py tests/search_discovery/test_providers.py
git commit -m "feat: preserve route metadata on search results"
```

## Task 4: Execute One Route Per Source In CLI

**Files:**
- Modify: `src/search_discovery/cli.py`
- Test: `tests/search_discovery/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Add to `tests/search_discovery/test_cli.py`:

```python
import json

from src.search_discovery.cli import run_discovery_command
from src.search_discovery.providers import MockProvider, SearchProviderRegistry


class RecordingProvider:
    source_id = "github_search"

    def __init__(self):
        self.queries = []

    def search_rows(self, query, **kwargs):
        self.queries.append(query)
        return [
            {
                "result_id": "github_1",
                "title": "example/agent-framework",
                "url": "https://github.com/example/agent-framework",
                "snippet": "Agent framework",
                "content_type": "repo",
            }
        ]


def test_run_discovery_command_calls_each_source_once(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "track_tags": ["AI", "开发者工具", "开源项目"],
                "custom_keywords": ["AI Agent", "MCP", "RAG"],
                "content_goal": "寻找近期技术趋势和项目",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    github = RecordingProvider()
    registry = SearchProviderRegistry(
        [
            github,
            MockProvider("juejin_content", rows=[]),
            MockProvider("baidu_qianfan_search", rows=[]),
            MockProvider("news_api_cn", rows=[]),
        ]
    )
    monkeypatch.setattr("src.search_discovery.cli._build_registry", lambda: registry)

    run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=True)

    assert github.queries == [
        "AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01"
    ]
    raw_rows = [
        json.loads(line)
        for line in (tmp_path / "data/search_discovery/raw/search_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    queries_by_source = {}
    for row in raw_rows:
        queries_by_source.setdefault(row["source_id"], set()).add(row["query"])
    assert all(len(queries) == 1 for queries in queries_by_source.values())
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_cli.py::test_run_discovery_command_calls_each_source_once -q
```

Expected: FAIL because the CLI currently executes multiple query bundles per source.

- [ ] **Step 3: Refactor CLI orchestration**

In `src/search_discovery/cli.py`:

Remove imports:

```python
from src.search_discovery.config import plan_sources_for_category, profile_source_weights, source_registry
from src.search_discovery.keywords import classify_keywords, generate_query_bundles
```

Add imports:

```python
from src.search_discovery.config import profile_source_weights
from src.search_discovery.routing import build_search_routes
```

Replace the nested bundle loop in `run_discovery_command` with:

```python
    routes = build_search_routes(profile)
    registry = _build_registry()
    results = []
    unavailable_ids = {
        sid for sid, provider in registry.providers.items()
        if isinstance(provider, MockProvider)
    }
    for counter, route in enumerate(routes):
        if route.source_id in unavailable_ids:
            marker_rows = _emit_unavailable_markers(
                registry_source_ids=[route.source_id],
                query=route.query,
                category=route.intent,
                fetched_at=generated_at,
                index=counter,
            )
            rows = normalize_provider_rows(
                rows=[
                    {
                        **row,
                        "route_weight": route.weight,
                        "route_reason": route.reason,
                        "matched_keywords": _matched_keywords(profile, row.get("title", ""), row.get("snippet", "")),
                    }
                    for row in marker_rows
                ],
                source_id=route.source_id,
                source_role=route.source_role,
                query=route.query,
                keyword_category=route.intent,
                fetched_at=generated_at,
            )
            results.extend(rows)
            continue

        rows = registry.search(
            source_id=route.source_id,
            source_role=route.source_role,
            query=route.query,
            keyword_category=route.intent,
            fetched_at=generated_at,
            index=counter,
        )
        results.extend(
            [
                SearchResult(
                    **{
                        **result.to_dict(),
                        "route_weight": route.weight,
                        "route_reason": route.reason,
                        "matched_keywords": _matched_keywords(profile, result.title, result.snippet),
                    }
                )
                for result in rows
            ]
        )
```

Add helper near `_now_shanghai`:

```python
def _matched_keywords(profile: CreatorProfile, title: str, snippet: str) -> list[str]:
    haystack = f"{title} {snippet}".lower()
    return [
        keyword
        for keyword in profile.all_keywords()
        if keyword.lower() in haystack
    ]
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_cli.py tests/search_discovery/test_cli_fallback.py -q
```

Expected: PASS. If an older fallback test expects four unavailable rows per query, update the expected count to one row per route/source.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/cli.py tests/search_discovery/test_cli.py tests/search_discovery/test_cli_fallback.py
git commit -m "feat: execute one search route per source"
```

## Task 5: Use Dynamic Route Weights In Topic Clustering

**Files:**
- Modify: `src/search_discovery/discovery.py`
- Test: `tests/search_discovery/test_discovery.py`

- [ ] **Step 1: Write failing discovery test**

Add to `tests/search_discovery/test_discovery.py`:

```python
from src.search_discovery.discovery import cluster_results
from src.search_discovery.types import CreatorProfile, SearchResult


def test_cluster_results_prefers_result_route_weight_over_profile_weight():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "custom_keywords": ["AI Agent"],
        }
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent in:name,description stars:>50 pushed:>2025-01-01",
            keyword_category="tech_project",
            title="AI Agent Framework",
            url="https://github.com/example/agent-framework",
            snippet="AI Agent framework",
            content_type="repo",
            route_weight=100,
            route_reason="dynamic route",
        )
    ]

    topics = cluster_results(profile, results, [], source_weights={"github_search": 80})

    assert topics[0].source_hits[0]["source_weight"] == 100
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_discovery.py::test_cluster_results_prefers_result_route_weight_over_profile_weight -q
```

Expected: FAIL because `_source_hits` uses only `source_weights`.

- [ ] **Step 3: Implement dynamic weight fallback**

In `src/search_discovery/discovery.py`, update `_source_hits` source weight assignment:

```python
                "source_weight": result.route_weight or source_weights.get(result.source_id, 0),
                "route_reason": result.route_reason,
```

- [ ] **Step 4: Run discovery tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_discovery.py tests/search_discovery/test_ranking.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/discovery.py tests/search_discovery/test_discovery.py
git commit -m "feat: rank topics with dynamic route weights"
```

## Task 6: Render Creator-facing Reference Report

**Files:**
- Modify: `src/search_discovery/render.py`
- Test: `tests/search_discovery/test_render.py`

- [ ] **Step 1: Write failing render test**

Update or add this test in `tests/search_discovery/test_render.py`:

```python
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CandidateTopic


def test_render_topics_markdown_outputs_creator_reference_fields():
    topic = CandidateTopic(
        topic_id="t1",
        title="AI Agent 开源项目仍在快速更新",
        matched_keywords=["AI Agent", "MCP"],
        keyword_categories=["tech_project"],
        profile_match_score=90,
        freshness="ongoing",
        detail_level="high",
        risk_level="low",
        source_hits=[
            {
                "source_id": "github_search",
                "title": "example/agent-framework",
                "url": "https://github.com/example/agent-framework",
                "content_type": "repo",
                "source_weight": 100,
                "route_reason": "科技类创作者关注开源项目，GitHub 适合召回 repo。",
            }
        ],
        summary="多个开源项目结果显示 AI Agent 工具链仍在活跃更新。",
        topic_score=88,
    )

    markdown = render_topics_markdown([topic], generated_at="2026-06-29T12:00:00+08:00")

    assert "匹配原因" in markdown
    assert "关键信息" in markdown
    assert "创作角度" in markdown
    assert "证据来源" in markdown
    assert "可信度" in markdown
    assert "风险提示" in markdown
    assert "https://github.com/example/agent-framework" in markdown
```

- [ ] **Step 2: Run failing render test**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_render.py::test_render_topics_markdown_outputs_creator_reference_fields -q
```

Expected: FAIL if report lacks the creator-facing sections.

- [ ] **Step 3: Implement report sections**

Update `render_topics_markdown` body to render each topic like:

```python
def render_topics_markdown(topics: list[CandidateTopic], generated_at: str) -> str:
    lines = [
        "# Search Topic Recommendations",
        "",
        f"Generated at: `{generated_at}`",
        "",
    ]
    if not topics:
        lines.extend(["No usable search topics were found.", ""])
        return "\n".join(lines)

    for index, topic in enumerate(topics, start=1):
        confidence = _confidence(topic)
        route_reason = _first_nonempty([str(hit.get("route_reason", "")) for hit in topic.source_hits])
        lines.extend(
            [
                f"## {index}. {topic.title}",
                "",
                f"- 匹配原因：{route_reason or '该话题命中了用户关键词，并有可追溯搜索来源。'}",
                f"- 关键信息：{topic.summary}",
                "- 创作角度：",
                f"  - 围绕 `{', '.join(topic.matched_keywords) or topic.title}` 做趋势观察或项目盘点。",
                "  - 结合来源链接补充案例、时间线和使用场景。",
                "- 证据来源：",
            ]
        )
        for hit in topic.source_hits:
            title = str(hit.get("title", "untitled"))
            url = str(hit.get("url", ""))
            source_id = str(hit.get("source_id", ""))
            if url:
                lines.append(f"  - `{source_id}` [{title}]({url})")
        lines.extend(
            [
                f"- 可信度：{confidence}",
                f"- 风险提示：{_risk_note(topic.risk_level)}",
                "",
            ]
        )
    return "\n".join(lines)


def _confidence(topic: CandidateTopic) -> str:
    if topic.detail_level == "high" and topic.source_hits:
        return "高"
    if topic.source_hits:
        return "中"
    return "低"


def _risk_note(risk_level: str) -> str:
    if risk_level == "high":
        return "该话题涉及高风险内容，生成前需要人工核验事实和措辞。"
    if risk_level == "medium":
        return "建议核验来源发布时间和关键事实，避免过度推断。"
    return "低风险，但不要把单一来源扩大为行业共识。"


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        if value.strip():
            return value.strip()
    return ""
```

- [ ] **Step 4: Run render tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_render.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/render.py tests/search_discovery/test_render.py
git commit -m "feat: render creator search reference report"
```

## Task 7: End-to-end Verification And Existing Test Alignment

**Files:**
- Modify tests only if existing assertions still describe the old multi-query behavior.
- Do not modify old DailyHot output paths.

- [ ] **Step 1: Run all search discovery tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery -q
```

Expected: PASS. Existing tests that intentionally check old multi-query behavior should be updated to the new rule: one query per source per request.

- [ ] **Step 2: Run the CLI against the tech AI profile**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.cli --profile config/search_discovery/creator_profiles/tech_ai_creator.json --render-report
```

Expected: JSON output similar to:

```json
{"evidence_count": 0, "search_results_count": 4, "topics_count": 0}
```

The exact counts depend on configured API keys. The important invariant is that every available source has exactly one query.

- [ ] **Step 3: Verify one query per source in raw output**

Run:

```powershell
@'
import json
from collections import defaultdict
path = r"E:\.code\My\heatedTopics\heatedTopics\data\search_discovery\raw\search_results.jsonl"
queries = defaultdict(set)
with open(path, encoding="utf-8") as f:
    for line in f:
        row = json.loads(line)
        queries[row["source_id"]].add(row["query"])
print({source: sorted(values) for source, values in queries.items()})
assert all(len(values) == 1 for values in queries.values())
'@ | python -
```

Expected: prints a dict where each `source_id` maps to one query, then exits without assertion error.

- [ ] **Step 4: Verify isolated outputs**

Run:

```powershell
Test-Path data/search_discovery/raw/search_results.jsonl
Test-Path data/search_discovery/evidence/search_content_evidence.jsonl
Test-Path data/search_discovery/processed/search_topic_index.json
Test-Path reports/search_discovery/search_topic_recommendations.md
```

Expected: all four commands print `True`.

- [ ] **Step 5: Commit final test alignment**

```powershell
git status --short
git add tests/search_discovery src/search_discovery
git commit -m "test: verify profile driven search routing"
```

Only include files touched for this feature. Do not stage unrelated dirty files from the older pipeline.

## Self-review

- Spec coverage: The plan covers profile input, dynamic intent, dynamic route weights, per-source query generation, one call per source, standard metadata, report output, unavailable provider handling, and isolated output paths.
- Placeholder scan: No task uses `TBD`, `TODO`, or undefined future work as an implementation instruction.
- Type consistency: `SearchRoute`, `route_weight`, `route_reason`, and `matched_keywords` are introduced in Task 1 and reused consistently in later tasks.
- Scope: LLM API integration remains template-based in this plan, matching the spec's first-version rule that LLM is optional and must not block search.

