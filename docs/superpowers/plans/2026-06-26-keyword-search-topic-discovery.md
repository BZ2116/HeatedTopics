# Keyword Search Topic Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated first version of keyword-driven topic discovery that starts from creator profiles, calls provider-style search adapters, clusters detailed results, ranks candidate topics, and renders JSON/Markdown outputs.

**Architecture:** All new runtime code lives under `src/search_discovery/` and all new tests live under `tests/search_discovery/`. The existing `src/core_pipeline/` DailyHot pipeline is not modified; the new feature has its own CLI entrypoint at `python -m src.search_discovery.cli`.

**Tech Stack:** Python 3.10+, standard library dataclasses/json/argparse/urllib, pytest. No new package dependency is required for v0.1.

---

## File Structure

Create a separate package:

```text
src/search_discovery/
  __init__.py
  cli.py
  config.py
  discovery.py
  enrich.py
  io.py
  keywords.py
  providers.py
  ranking.py
  render.py
  types.py
```

Create isolated tests:

```text
tests/search_discovery/
  __init__.py
  test_cli.py
  test_config.py
  test_discovery.py
  test_enrich.py
  test_keywords.py
  test_providers.py
  test_ranking.py
  test_render.py
```

Create example config:

```text
config/search_discovery/creator_profiles/tech_ai_creator.json
```

Output paths for the new feature:

```text
data/search_discovery/raw/search_results.jsonl
data/search_discovery/evidence/search_content_evidence.jsonl
data/search_discovery/processed/search_topic_index.json
reports/search_discovery/search_topic_recommendations.md
```

These paths deliberately avoid the existing `data/raw/dailyhot_records.json`, `data/evidence/detail_evidence_raw.jsonl`, `data/processed/creator_topic_index.json`, and `reports/creator_topic_cards.md` files.

---

### Task 1: Package Skeleton and Data Types

**Files:**
- Create: `src/search_discovery/__init__.py`
- Create: `src/search_discovery/types.py`
- Create: `tests/search_discovery/__init__.py`
- Create: `tests/search_discovery/test_types.py`

- [ ] **Step 1: Write the failing data type tests**

Create `tests/search_discovery/test_types.py`:

```python
from src.search_discovery.types import CandidateTopic, CreatorProfile, SearchResult


def test_creator_profile_from_dict_uses_empty_defaults():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "custom_keywords": ["AI Agent"],
        }
    )

    assert profile.creator_id == "creator_001"
    assert profile.track_tags == []
    assert profile.content_modes == []


def test_search_result_rejects_title_only_result():
    result = SearchResult(
        result_id="r1",
        source_id="mock",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        title="只有标题",
    )

    assert result.has_usable_detail() is False


def test_candidate_topic_serializes_source_hits():
    topic = CandidateTopic(
        topic_id="topic_001",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=88,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[
            {
                "source_id": "github_search",
                "title": "example/agent",
                "url": "https://github.com/example/agent",
                "content_type": "repo",
                "source_weight": 95,
            }
        ],
        summary="GitHub 和文章结果共同指向该话题。",
    )

    row = topic.to_dict()

    assert row["topic_id"] == "topic_001"
    assert row["source_hits"][0]["source_id"] == "github_search"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_types.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.search_discovery'`.

- [ ] **Step 3: Create package files**

Create `src/search_discovery/__init__.py`:

```python
"""Keyword-driven topic discovery package."""
```

Create `tests/search_discovery/__init__.py`:

```python
"""Tests for keyword-driven topic discovery."""
```

Create `src/search_discovery/types.py`:

```python
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreatorProfile:
    creator_id: str
    role: str
    profile_type: str
    track_tags: list[str] = field(default_factory=list)
    custom_keywords: list[str] = field(default_factory=list)
    content_modes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "CreatorProfile":
        return cls(
            creator_id=str(row.get("creator_id", "")),
            role=str(row.get("role", "")),
            profile_type=str(row.get("profile_type", "")),
            track_tags=[str(item) for item in row.get("track_tags", [])],
            custom_keywords=[str(item) for item in row.get("custom_keywords", [])],
            content_modes=[str(item) for item in row.get("content_modes", [])],
        )

    def all_keywords(self) -> list[str]:
        values = [*self.track_tags, *self.custom_keywords]
        return _unique_nonempty(values)


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    source_role: str
    detail_level: str
    default_weight: int
    stability: str = "stable"
    enabled: bool = True


@dataclass(frozen=True)
class QueryBundle:
    category: str
    queries: list[str]


@dataclass(frozen=True)
class PlannedSource:
    source_id: str
    weight: int


@dataclass(frozen=True)
class SearchResult:
    result_id: str
    source_id: str
    source_role: str
    query: str
    keyword_category: str
    title: str
    url: str = ""
    domain: str = ""
    snippet: str = ""
    content_type: str = "unknown"
    published_at: str = ""
    fetched_at: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    fetch_status: str = "ok"
    error_type: str | None = None

    def has_usable_detail(self) -> bool:
        return bool(self.url and (self.snippet or self.raw_payload or self.content_type == "repo"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnrichedContent:
    result_id: str
    url: str
    title: str
    content: str
    author: str = ""
    published_at: str = ""
    content_quality: str = "low"
    extraction_method: str = "provider_snippet_or_reader"
    evidence_confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateTopic:
    topic_id: str
    title: str
    matched_keywords: list[str]
    keyword_categories: list[str]
    profile_match_score: int
    freshness: str
    detail_level: str
    risk_level: str
    source_hits: list[dict[str, Any]]
    summary: str
    open_questions: list[str] = field(default_factory=list)
    created_at: str = ""
    topic_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unique_nonempty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_types.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/__init__.py src/search_discovery/types.py tests/search_discovery/__init__.py tests/search_discovery/test_types.py
git commit -m "feat: add search discovery data types"
```

---

### Task 2: Static Config and Source Planning

**Files:**
- Create: `src/search_discovery/config.py`
- Create: `tests/search_discovery/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/search_discovery/test_config.py`:

```python
from src.search_discovery.config import (
    keyword_categories,
    plan_sources_for_category,
    profile_source_weights,
    source_registry,
)


def test_source_registry_marks_dailyhot_as_reference_only():
    sources = source_registry()

    assert sources["dailyhot_reference"].source_role == "heat_reference"
    assert sources["dailyhot_reference"].default_weight == 25


def test_tech_ai_profile_weights_github_above_baidu():
    weights = profile_source_weights("tech_ai_creator")

    assert weights["github_search"] == 95
    assert weights["github_search"] > weights["baidu_qianfan_search"]


def test_keyword_categories_include_tech_project_sources():
    categories = keyword_categories()

    assert categories["tech_project"]["preferred_sources"] == ["github_search", "juejin_content"]


def test_plan_sources_uses_profile_and_category_preference_order():
    planned = plan_sources_for_category("tech_ai_creator", "tech_project")

    assert [source.source_id for source in planned] == ["github_search", "juejin_content"]
    assert [source.weight for source in planned] == [95, 90]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_config.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.search_discovery.config'`.

- [ ] **Step 3: Implement config**

Create `src/search_discovery/config.py`:

```python
from src.search_discovery.types import PlannedSource, SourceConfig


def source_registry() -> dict[str, SourceConfig]:
    return {
        "baidu_qianfan_search": SourceConfig("baidu_qianfan_search", "primary_search", "medium", 90),
        "news_api_cn": SourceConfig("news_api_cn", "news_search", "medium_high", 85),
        "github_search": SourceConfig("github_search", "vertical_project", "high", 80),
        "juejin_content": SourceConfig("juejin_content", "vertical_article", "medium_high", 75, stability="experimental"),
        "serpapi_baidu": SourceConfig("serpapi_baidu", "serp_fallback", "medium", 65),
        "dataforseo_baidu": SourceConfig("dataforseo_baidu", "serp_fallback", "medium", 60),
        "searchapi_baidu": SourceConfig("searchapi_baidu", "serp_fallback", "medium", 60),
        "dailyhot_reference": SourceConfig("dailyhot_reference", "heat_reference", "low", 25),
    }


PROFILE_SOURCE_WEIGHTS = {
    "tech_ai_creator": {
        "baidu_qianfan_search": 80,
        "news_api_cn": 60,
        "github_search": 95,
        "juejin_content": 90,
        "serpapi_baidu": 55,
        "dailyhot_reference": 20,
    },
    "developer_creator": {
        "baidu_qianfan_search": 70,
        "news_api_cn": 40,
        "github_search": 100,
        "juejin_content": 95,
        "serpapi_baidu": 50,
        "dailyhot_reference": 15,
    },
    "business_startup_creator": {
        "baidu_qianfan_search": 85,
        "news_api_cn": 90,
        "github_search": 35,
        "juejin_content": 30,
        "serpapi_baidu": 60,
        "dailyhot_reference": 20,
    },
    "general_hot_topic_creator": {
        "baidu_qianfan_search": 95,
        "news_api_cn": 90,
        "github_search": 5,
        "juejin_content": 5,
        "serpapi_baidu": 65,
        "dailyhot_reference": 35,
    },
}


def profile_source_weights(profile_type: str) -> dict[str, int]:
    return PROFILE_SOURCE_WEIGHTS.get(profile_type, PROFILE_SOURCE_WEIGHTS["general_hot_topic_creator"])


def keyword_categories() -> dict[str, dict[str, list[str]]]:
    return {
        "topic_discovery": {
            "terms": ["最新", "热点", "热议", "趋势", "爆火", "刷屏", "今日", "刚刚", "新进展"],
            "preferred_sources": ["baidu_qianfan_search", "news_api_cn"],
        },
        "news_article": {
            "terms": ["新闻", "报道", "官方回应", "通报", "发布", "调查", "进展", "事件"],
            "preferred_sources": ["news_api_cn", "baidu_qianfan_search"],
        },
        "deep_article": {
            "terms": ["分析", "解读", "复盘", "观点", "原因", "影响", "争议", "长文"],
            "preferred_sources": ["baidu_qianfan_search", "juejin_content", "news_api_cn"],
        },
        "tech_project": {
            "terms": ["GitHub", "开源", "框架", "工具", "库", "repo", "star", "release"],
            "preferred_sources": ["github_search", "juejin_content"],
        },
        "tech_tutorial": {
            "terms": ["教程", "实践", "案例", "源码", "部署", "测评", "对比", "最佳实践"],
            "preferred_sources": ["juejin_content", "github_search", "baidu_qianfan_search"],
        },
        "risk_sensitive": {
            "terms": ["医疗", "投资", "未成年", "事故", "案件", "违法", "辟谣", "监管"],
            "preferred_sources": ["news_api_cn", "baidu_qianfan_search"],
        },
    }


def plan_sources_for_category(profile_type: str, category: str, limit: int = 3) -> list[PlannedSource]:
    categories = keyword_categories()
    weights = profile_source_weights(profile_type)
    preferred = categories.get(category, categories["topic_discovery"])["preferred_sources"]
    planned = [
        PlannedSource(source_id=source_id, weight=weights.get(source_id, 0))
        for source_id in preferred
        if weights.get(source_id, 0) > 0
    ]
    return planned[:limit]
```

- [ ] **Step 4: Run the tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/config.py tests/search_discovery/test_config.py
git commit -m "feat: add search discovery source config"
```

---

### Task 3: Keyword Classification and Query Generation

**Files:**
- Create: `src/search_discovery/keywords.py`
- Create: `tests/search_discovery/test_keywords.py`

- [ ] **Step 1: Write failing keyword tests**

Create `tests/search_discovery/test_keywords.py`:

```python
from src.search_discovery.keywords import classify_keywords, generate_query_bundles
from src.search_discovery.types import CreatorProfile


def test_classify_tech_profile_adds_project_and_tutorial_categories():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        track_tags=["AI", "开发者工具", "开源项目"],
        custom_keywords=["AI Agent", "MCP"],
        content_modes=["教程实践"],
    )

    categories = classify_keywords(profile)

    assert "topic_discovery" in categories
    assert "tech_project" in categories
    assert "tech_tutorial" in categories


def test_generate_query_bundles_uses_category_templates():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent"],
    )

    bundles = generate_query_bundles(profile, categories=["topic_discovery", "tech_project"])

    by_category = {bundle.category: bundle.queries for bundle in bundles}
    assert "AI Agent 最新进展" in by_category["topic_discovery"]
    assert "AI Agent GitHub" in by_category["tech_project"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_keywords.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.search_discovery.keywords'`.

- [ ] **Step 3: Implement keyword classification and query generation**

Create `src/search_discovery/keywords.py`:

```python
from src.search_discovery.types import CreatorProfile, QueryBundle


QUERY_TEMPLATES = {
    "topic_discovery": ["{keyword} 最新进展", "{keyword} 热点", "{keyword} 今日", "{keyword} 趋势"],
    "news_article": ["{keyword} 新闻", "{keyword} 官方回应", "{keyword} 最新报道", "{keyword} 进展"],
    "deep_article": ["{keyword} 分析", "{keyword} 解读", "{keyword} 影响", "{keyword} 复盘"],
    "tech_project": ["{keyword} GitHub", "{keyword} open source", "{keyword} repo", "{keyword} release"],
    "tech_tutorial": ["{keyword} 教程", "{keyword} 实践", "{keyword} 案例", "{keyword} 源码"],
    "risk_sensitive": ["{keyword} 官方消息", "{keyword} 辟谣", "{keyword} 风险", "{keyword} 监管"],
}


def classify_keywords(profile: CreatorProfile) -> list[str]:
    text = " ".join([profile.role, profile.profile_type, *profile.track_tags, *profile.custom_keywords, *profile.content_modes]).lower()
    categories = ["topic_discovery"]
    if any(term.lower() in text for term in ["新闻", "报道", "通报", "官方"]):
        categories.append("news_article")
    if any(term.lower() in text for term in ["分析", "解读", "复盘", "观点"]):
        categories.append("deep_article")
    if any(term.lower() in text for term in ["ai", "github", "开源", "开发者", "工具", "agent", "mcp", "rag"]):
        categories.append("tech_project")
    if any(term.lower() in text for term in ["教程", "实践", "源码", "部署", "案例"]):
        categories.append("tech_tutorial")
    if any(term.lower() in text for term in ["医疗", "投资", "事故", "案件", "未成年", "监管"]):
        categories.append("risk_sensitive")
    return _unique(categories)


def generate_query_bundles(
    profile: CreatorProfile,
    categories: list[str] | None = None,
    max_queries_per_category: int = 6,
) -> list[QueryBundle]:
    selected_categories = categories or classify_keywords(profile)
    keywords = profile.all_keywords() or profile.custom_keywords or profile.track_tags
    bundles: list[QueryBundle] = []
    for category in selected_categories:
        templates = QUERY_TEMPLATES.get(category, QUERY_TEMPLATES["topic_discovery"])
        queries = []
        for keyword in keywords:
            for template in templates:
                queries.append(template.format(keyword=keyword))
        bundles.append(QueryBundle(category=category, queries=_unique(queries)[:max_queries_per_category]))
    return bundles


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
```

- [ ] **Step 4: Run the tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_keywords.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/keywords.py tests/search_discovery/test_keywords.py
git commit -m "feat: generate search discovery queries"
```

---

### Task 4: Provider Interface and Mockable Providers

**Files:**
- Create: `src/search_discovery/providers.py`
- Create: `tests/search_discovery/test_providers.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/search_discovery/test_providers.py`:

```python
from src.search_discovery.providers import MockProvider, SearchProviderRegistry, normalize_provider_rows


def test_normalize_provider_rows_discards_title_only_rows():
    rows = [
        {"title": "只有标题"},
        {"title": "AI Agent 新闻", "url": "https://example.com/a", "snippet": "发布新功能"},
    ]

    results = normalize_provider_rows(
        rows=rows,
        source_id="baidu_qianfan_search",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        fetched_at="2026-06-26T12:00:00+08:00",
    )

    assert len(results) == 1
    assert results[0].title == "AI Agent 新闻"


def test_registry_calls_matching_provider():
    provider = MockProvider(
        source_id="baidu_qianfan_search",
        rows=[{"title": "AI Agent 新闻", "url": "https://example.com/a", "snippet": "发布新功能"}],
    )
    registry = SearchProviderRegistry([provider])

    results = registry.search(
        source_id="baidu_qianfan_search",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        fetched_at="2026-06-26T12:00:00+08:00",
    )

    assert results[0].source_id == "baidu_qianfan_search"
    assert results[0].url == "https://example.com/a"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_providers.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.search_discovery.providers'`.

- [ ] **Step 3: Implement provider abstractions**

Create `src/search_discovery/providers.py`:

```python
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from src.search_discovery.types import SearchResult


class SearchProvider(Protocol):
    source_id: str

    def search_rows(self, query: str) -> list[dict[str, object]]:
        raise NotImplementedError


@dataclass
class MockProvider:
    source_id: str
    rows: list[dict[str, object]]

    def search_rows(self, query: str) -> list[dict[str, object]]:
        return self.rows


class SearchProviderRegistry:
    def __init__(self, providers: list[SearchProvider]) -> None:
        self._providers = {provider.source_id: provider for provider in providers}

    def search(
        self,
        source_id: str,
        source_role: str,
        query: str,
        keyword_category: str,
        fetched_at: str,
    ) -> list[SearchResult]:
        provider = self._providers.get(source_id)
        if provider is None:
            return []
        rows = provider.search_rows(query)
        return normalize_provider_rows(rows, source_id, source_role, query, keyword_category, fetched_at)


def normalize_provider_rows(
    rows: list[dict[str, object]],
    source_id: str,
    source_role: str,
    query: str,
    keyword_category: str,
    fetched_at: str,
) -> list[SearchResult]:
    results = []
    for index, row in enumerate(rows, start=1):
        title = str(row.get("title", "")).strip()
        url = str(row.get("url", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        content_type = str(row.get("content_type", "unknown")).strip() or "unknown"
        result = SearchResult(
            result_id=f"{source_id}_{index:03d}",
            source_id=source_id,
            source_role=source_role,
            query=query,
            keyword_category=keyword_category,
            title=title,
            url=url,
            domain=_domain(url),
            snippet=snippet,
            content_type=content_type,
            published_at=str(row.get("published_at", "")),
            fetched_at=fetched_at,
            metrics=row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {},
            raw_payload=dict(row),
        )
        if result.has_usable_detail():
            results.append(result)
    return results


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc
```

- [ ] **Step 4: Run the tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_providers.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/providers.py tests/search_discovery/test_providers.py
git commit -m "feat: add search provider normalization"
```

---

### Task 5: Enrichment, Clustering, and Ranking

**Files:**
- Create: `src/search_discovery/enrich.py`
- Create: `src/search_discovery/ranking.py`
- Create: `src/search_discovery/discovery.py`
- Create: `tests/search_discovery/test_enrich.py`
- Create: `tests/search_discovery/test_ranking.py`
- Create: `tests/search_discovery/test_discovery.py`

- [ ] **Step 1: Write failing enrichment tests**

Create `tests/search_discovery/test_enrich.py`:

```python
from src.search_discovery.enrich import enrich_results
from src.search_discovery.types import SearchResult


def test_enrich_results_uses_snippet_as_content_when_reader_missing():
    result = SearchResult(
        result_id="r1",
        source_id="baidu_qianfan_search",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        title="AI Agent 新闻",
        url="https://example.com/a",
        snippet="发布新功能",
        content_type="news",
    )

    enriched = enrich_results([result])

    assert enriched[0].content == "发布新功能"
    assert enriched[0].content_quality == "medium"
```

- [ ] **Step 2: Write failing ranking tests**

Create `tests/search_discovery/test_ranking.py`:

```python
from src.search_discovery.ranking import score_topic
from src.search_discovery.types import CandidateTopic


def test_score_topic_rewards_detail_and_source_weight():
    topic = CandidateTopic(
        topic_id="topic_001",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=90,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[{"source_weight": 95}, {"source_weight": 80}],
        summary="有多个来源。",
    )

    assert score_topic(topic) >= 80


def test_score_topic_penalizes_sensitive_risk():
    low_risk = CandidateTopic(
        topic_id="topic_low",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=90,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[{"source_weight": 95}],
        summary="低风险。",
    )
    high_risk = CandidateTopic(
        topic_id="topic_high",
        title="投资医疗争议事件",
        matched_keywords=["投资"],
        keyword_categories=["risk_sensitive"],
        profile_match_score=90,
        freshness="breaking",
        detail_level="high",
        risk_level="high",
        source_hits=[{"source_weight": 95}],
        summary="高风险。",
    )

    assert score_topic(low_risk) > score_topic(high_risk)
```

- [ ] **Step 3: Write failing discovery tests**

Create `tests/search_discovery/test_discovery.py`:

```python
from src.search_discovery.discovery import cluster_results
from src.search_discovery.types import CreatorProfile, EnrichedContent, SearchResult


def test_cluster_results_groups_by_keyword_and_title_overlap():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent"],
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent GitHub",
            keyword_category="tech_project",
            title="AI Agent framework",
            url="https://github.com/example/agent",
            snippet="开源 agent framework",
            content_type="repo",
        )
    ]
    contents = [
        EnrichedContent(
            result_id="r1",
            url="https://github.com/example/agent",
            title="AI Agent framework",
            content="开源 agent framework",
            content_quality="high",
            evidence_confidence="high",
        )
    ]

    topics = cluster_results(profile, results, contents, source_weights={"github_search": 95})

    assert len(topics) == 1
    assert topics[0].matched_keywords == ["AI Agent"]
    assert topics[0].detail_level == "high"
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_enrich.py tests/search_discovery/test_ranking.py tests/search_discovery/test_discovery.py -q
```

Expected: FAIL because `enrich.py`, `ranking.py`, and `discovery.py` do not exist.

- [ ] **Step 5: Implement enrichment**

Create `src/search_discovery/enrich.py`:

```python
from collections.abc import Callable

from src.search_discovery.types import EnrichedContent, SearchResult


PageReader = Callable[[str], str]


def enrich_results(results: list[SearchResult], page_reader: PageReader | None = None) -> list[EnrichedContent]:
    enriched = []
    for result in results:
        content = ""
        method = "provider_snippet_or_reader"
        if page_reader is not None and result.url:
            try:
                content = page_reader(result.url).strip()
                method = "reader"
            except Exception:
                content = ""
        if not content:
            content = result.snippet.strip()
        quality = _content_quality(content, result.content_type)
        enriched.append(
            EnrichedContent(
                result_id=result.result_id,
                url=result.url,
                title=result.title,
                content=content,
                author=str(result.raw_payload.get("author", "")),
                published_at=result.published_at,
                content_quality=quality,
                extraction_method=method,
                evidence_confidence="high" if quality == "high" else "medium" if quality == "medium" else "low",
            )
        )
    return enriched


def _content_quality(content: str, content_type: str) -> str:
    if content_type == "repo" and content:
        return "high"
    if len(content) >= 300:
        return "high"
    if content:
        return "medium"
    return "low"
```

- [ ] **Step 6: Implement ranking**

Create `src/search_discovery/ranking.py`:

```python
from src.search_discovery.types import CandidateTopic


def score_topic(topic: CandidateTopic) -> int:
    source_score = _avg_source_weight(topic)
    profile_keyword_score = topic.profile_match_score
    detail_score = {"high": 95, "medium_high": 85, "medium": 70, "low": 25}.get(topic.detail_level, 40)
    freshness_score = {"breaking": 95, "ongoing": 80, "evergreen": 60, "fading": 30}.get(topic.freshness, 50)
    evidence_diversity_score = min(len(topic.source_hits), 4) * 25
    risk_penalty = {"low": 0, "medium": 30, "high": 70}.get(topic.risk_level, 20)
    score = (
        source_score * 0.25
        + profile_keyword_score * 0.25
        + detail_score * 0.20
        + freshness_score * 0.15
        + evidence_diversity_score * 0.10
        - risk_penalty * 0.05
    )
    return max(0, min(100, round(score)))


def _avg_source_weight(topic: CandidateTopic) -> float:
    weights = [
        int(hit.get("source_weight", 0))
        for hit in topic.source_hits
        if isinstance(hit.get("source_weight", 0), int)
    ]
    if not weights:
        return 0
    return sum(weights) / len(weights)
```

- [ ] **Step 7: Implement clustering**

Create `src/search_discovery/discovery.py`:

```python
from datetime import datetime, timezone, timedelta

from src.search_discovery.ranking import score_topic
from src.search_discovery.types import CandidateTopic, CreatorProfile, EnrichedContent, SearchResult


def cluster_results(
    profile: CreatorProfile,
    results: list[SearchResult],
    contents: list[EnrichedContent],
    source_weights: dict[str, int],
) -> list[CandidateTopic]:
    content_by_result_id = {content.result_id: content for content in contents}
    topics = []
    for index, result in enumerate(results, start=1):
        content = content_by_result_id.get(result.result_id)
        text = " ".join([result.title, result.snippet, content.content if content else ""])
        matched_keywords = _matched_keywords(profile.all_keywords(), text)
        detail_level = content.content_quality if content is not None else "low"
        risk_level = _risk_level(text)
        source_hit = {
            "source_id": result.source_id,
            "title": result.title,
            "url": result.url,
            "content_type": result.content_type,
            "source_weight": source_weights.get(result.source_id, 0),
        }
        topic = CandidateTopic(
            topic_id=f"search_topic_{index:03d}",
            title=result.title,
            matched_keywords=matched_keywords,
            keyword_categories=[result.keyword_category],
            profile_match_score=_profile_match_score(matched_keywords, profile.all_keywords()),
            freshness="breaking" if result.published_at or "最新" in result.query else "ongoing",
            detail_level=detail_level,
            risk_level=risk_level,
            source_hits=[source_hit],
            summary=_summary(result, content),
            created_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        )
        topics.append(
            CandidateTopic(
                **{**topic.to_dict(), "topic_score": score_topic(topic)}
            )
        )
    return sorted(topics, key=lambda row: row.topic_score, reverse=True)


def _matched_keywords(keywords: list[str], text: str) -> list[str]:
    normalized = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in normalized]


def _profile_match_score(matched_keywords: list[str], all_keywords: list[str]) -> int:
    if not all_keywords:
        return 50
    return round(len(matched_keywords) / len(all_keywords) * 100)


def _risk_level(text: str) -> str:
    high_terms = ["案件", "违法", "未成年", "事故"]
    medium_terms = ["医疗", "投资", "监管", "争议", "辟谣"]
    if any(term in text for term in high_terms):
        return "high"
    if any(term in text for term in medium_terms):
        return "medium"
    return "low"


def _summary(result: SearchResult, content: EnrichedContent | None) -> str:
    detail = content.content if content is not None else result.snippet
    if detail:
        return detail[:160]
    return f"{result.title} 来自 {result.source_id}。"
```

- [ ] **Step 8: Run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_enrich.py tests/search_discovery/test_ranking.py tests/search_discovery/test_discovery.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/search_discovery/enrich.py src/search_discovery/ranking.py src/search_discovery/discovery.py tests/search_discovery/test_enrich.py tests/search_discovery/test_ranking.py tests/search_discovery/test_discovery.py
git commit -m "feat: rank keyword search topics"
```

---

### Task 6: JSONL IO and Markdown Rendering

**Files:**
- Create: `src/search_discovery/io.py`
- Create: `src/search_discovery/render.py`
- Create: `tests/search_discovery/test_render.py`

- [ ] **Step 1: Write failing render and IO tests**

Create `tests/search_discovery/test_render.py`:

```python
import json

from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CandidateTopic


def test_write_jsonl_creates_parent_directory(tmp_path):
    path = tmp_path / "data/search_discovery/raw/search_results.jsonl"

    write_jsonl(path, [{"title": "AI Agent 新闻"}])

    assert path.read_text(encoding="utf-8").strip() == '{"title": "AI Agent 新闻"}'


def test_write_json_creates_readable_json(tmp_path):
    path = tmp_path / "data/search_discovery/processed/search_topic_index.json"

    write_json(path, {"topics": [{"title": "AI Agent 新闻"}]})

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["topics"][0]["title"] == "AI Agent 新闻"


def test_render_topics_markdown_includes_source_urls():
    topic = CandidateTopic(
        topic_id="search_topic_001",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=88,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[
            {
                "source_id": "github_search",
                "title": "example/agent",
                "url": "https://github.com/example/agent",
                "content_type": "repo",
                "source_weight": 95,
            }
        ],
        summary="GitHub 项目热度提升。",
        topic_score=90,
    )

    markdown = render_topics_markdown([topic], generated_at="2026-06-26T12:00:00+08:00")

    assert "# 关键词搜索话题推荐" in markdown
    assert "https://github.com/example/agent" in markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_render.py -q
```

Expected: FAIL because `io.py` and `render.py` do not exist.

- [ ] **Step 3: Implement IO**

Create `src/search_discovery/io.py`:

```python
import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if rows else ""), encoding="utf-8")
```

- [ ] **Step 4: Implement Markdown renderer**

Create `src/search_discovery/render.py`:

```python
from src.search_discovery.types import CandidateTopic


def render_topics_markdown(topics: list[CandidateTopic], generated_at: str) -> str:
    lines = [
        "# 关键词搜索话题推荐",
        "",
        f"- 生成时间：{generated_at}",
        f"- 候选话题数：{len(topics)}",
        "",
    ]
    for index, topic in enumerate(topics, start=1):
        lines.extend(
            [
                f"## {index}. {topic.title}",
                "",
                f"- 分数：{topic.topic_score}",
                f"- 匹配关键词：{', '.join(topic.matched_keywords) or '无'}",
                f"- 关键词分类：{', '.join(topic.keyword_categories)}",
                f"- 新鲜度：{topic.freshness}",
                f"- 详情等级：{topic.detail_level}",
                f"- 风险等级：{topic.risk_level}",
                "",
                topic.summary,
                "",
                "### 来源",
            ]
        )
        for hit in topic.source_hits:
            title = str(hit.get("title", ""))
            url = str(hit.get("url", ""))
            source_id = str(hit.get("source_id", ""))
            lines.append(f"- `{source_id}` [{title}]({url})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 5: Run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_render.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/search_discovery/io.py src/search_discovery/render.py tests/search_discovery/test_render.py
git commit -m "feat: render search discovery outputs"
```

---

### Task 7: End-to-End Orchestrator and CLI

**Files:**
- Create: `src/search_discovery/cli.py`
- Create: `tests/search_discovery/test_cli.py`
- Create: `config/search_discovery/creator_profiles/tech_ai_creator.json`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/search_discovery/test_cli.py`:

```python
import json

from src.search_discovery.cli import run_discovery_command


def test_run_discovery_command_writes_isolated_outputs(tmp_path):
    profile_path = tmp_path / "config/search_discovery/creator_profiles/tech_ai_creator.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "track_tags": ["AI"],
                "custom_keywords": ["AI Agent"],
                "content_modes": ["教程实践"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    counts = run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=True)

    assert counts["search_results_count"] > 0
    assert (tmp_path / "data/search_discovery/raw/search_results.jsonl").exists()
    assert (tmp_path / "data/search_discovery/processed/search_topic_index.json").exists()
    assert (tmp_path / "reports/search_discovery/search_topic_recommendations.md").exists()
    assert not (tmp_path / "data/raw/dailyhot_records.json").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_cli.py -q
```

Expected: FAIL because `src.search_discovery.cli` does not exist.

- [ ] **Step 3: Create example profile**

Create `config/search_discovery/creator_profiles/tech_ai_creator.json`:

```json
{
  "creator_id": "creator_001",
  "role": "科技类博主",
  "profile_type": "tech_ai_creator",
  "track_tags": ["AI", "开发者工具", "开源项目"],
  "custom_keywords": ["AI Agent", "MCP", "RAG"],
  "content_modes": ["趋势观察", "工具测评", "教程实践"]
}
```

- [ ] **Step 4: Implement CLI command**

Create `src/search_discovery/cli.py`:

```python
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.search_discovery.config import plan_sources_for_category, profile_source_weights, source_registry
from src.search_discovery.discovery import cluster_results
from src.search_discovery.enrich import enrich_results
from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.keywords import classify_keywords, generate_query_bundles
from src.search_discovery.providers import MockProvider, SearchProviderRegistry
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CreatorProfile


def run_discovery_command(root: Path, profile_path: Path, render_report: bool = False) -> dict[str, int]:
    profile = CreatorProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    generated_at = _now_shanghai()
    categories = classify_keywords(profile)
    bundles = generate_query_bundles(profile, categories=categories)
    sources = source_registry()
    registry = _default_mock_registry()
    results = []
    for bundle in bundles:
        planned_sources = plan_sources_for_category(profile.profile_type, bundle.category)
        for planned_source in planned_sources:
            source = sources[planned_source.source_id]
            for query in bundle.queries:
                results.extend(
                    registry.search(
                        source_id=planned_source.source_id,
                        source_role=source.source_role,
                        query=query,
                        keyword_category=bundle.category,
                        fetched_at=generated_at,
                    )
                )
    enriched = enrich_results(results)
    source_weights = profile_source_weights(profile.profile_type)
    topics = cluster_results(profile, results, enriched, source_weights=source_weights)
    paths = _output_paths(root)
    write_jsonl(paths["raw_results"], [result.to_dict() for result in results])
    write_jsonl(paths["evidence"], [content.to_dict() for content in enriched])
    write_json(
        paths["topic_index"],
        {
            "schema_version": "0.1",
            "generated_at": generated_at,
            "profile": profile_path.as_posix(),
            "topics": [topic.to_dict() for topic in topics],
        },
    )
    if render_report:
        paths["report"].parent.mkdir(parents=True, exist_ok=True)
        paths["report"].write_text(render_topics_markdown(topics, generated_at), encoding="utf-8")
    return {
        "search_results_count": len(results),
        "evidence_count": len(enriched),
        "topics_count": len(topics),
    }


def _output_paths(root: Path) -> dict[str, Path]:
    return {
        "raw_results": root / "data/search_discovery/raw/search_results.jsonl",
        "evidence": root / "data/search_discovery/evidence/search_content_evidence.jsonl",
        "topic_index": root / "data/search_discovery/processed/search_topic_index.json",
        "report": root / "reports/search_discovery/search_topic_recommendations.md",
    }


def _default_mock_registry() -> SearchProviderRegistry:
    return SearchProviderRegistry(
        [
            MockProvider(
                "baidu_qianfan_search",
                [
                    {
                        "title": "AI Agent 最新进展：开源工具和产品能力同步升温",
                        "url": "https://example.com/ai-agent-news",
                        "snippet": "AI Agent 相关产品发布和开源项目近期持续增加。",
                        "content_type": "news",
                    }
                ],
            ),
            MockProvider(
                "news_api_cn",
                [
                    {
                        "title": "AI 工具行业出现新一轮产品发布",
                        "url": "https://example.com/ai-tool-news",
                        "snippet": "多家公司发布 AI 工具更新，开发者生态成为重点。",
                        "content_type": "news",
                    }
                ],
            ),
            MockProvider(
                "github_search",
                [
                    {
                        "title": "example/ai-agent-framework",
                        "url": "https://github.com/example/ai-agent-framework",
                        "snippet": "Open source AI Agent framework with tools and workflow support.",
                        "content_type": "repo",
                    }
                ],
            ),
            MockProvider(
                "juejin_content",
                [
                    {
                        "title": "AI Agent 掘金实践：从工具调用到工作流",
                        "url": "https://juejin.cn/post/example",
                        "snippet": "文章介绍 AI Agent 工程实践、工具调用和部署经验。",
                        "content_type": "article",
                    }
                ],
            ),
        ]
    )


def _now_shanghai() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--render-report", action="store_true")
    args = parser.parse_args()
    counts = run_discovery_command(Path("."), Path(args.profile), render_report=args.render_report)
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run CLI tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the new CLI manually**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.cli --profile config/search_discovery/creator_profiles/tech_ai_creator.json --render-report
```

Expected: prints JSON with positive `search_results_count`, `evidence_count`, and `topics_count`.

- [ ] **Step 7: Verify isolated outputs**

Run:

```powershell
Test-Path data/search_discovery/processed/search_topic_index.json
Test-Path reports/search_discovery/search_topic_recommendations.md
Test-Path data/raw/dailyhot_records.json
```

Expected: first two commands print `True`. The third command may print either `True` or `False` depending on old pipeline state; the new CLI must not create or modify that path.

- [ ] **Step 8: Commit**

```powershell
git add src/search_discovery/cli.py tests/search_discovery/test_cli.py config/search_discovery/creator_profiles/tech_ai_creator.json
git commit -m "feat: add isolated search discovery cli"
```

---

### Task 8: Full Verification and Documentation Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README section**

Append this section to `README.md`:

```markdown
## 关键词搜索话题发现

新链路从作者画像和关键词出发，通过独立的 `src/search_discovery/` 包生成搜索 query、规划搜索源、归一化结果、补全内容、聚合候选话题并输出报告。它不覆盖原有 DailyHot 热榜采集链路。

示例运行：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.cli --profile config/search_discovery/creator_profiles/tech_ai_creator.json --render-report
```

输出文件：

| 路径 | 内容 |
| --- | --- |
| `data/search_discovery/raw/search_results.jsonl` | 搜索源返回的归一化结果 |
| `data/search_discovery/evidence/search_content_evidence.jsonl` | 摘要或正文补全证据 |
| `data/search_discovery/processed/search_topic_index.json` | 候选话题索引 |
| `reports/search_discovery/search_topic_recommendations.md` | 可读推荐报告 |
```

- [ ] **Step 2: Run all new tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery -q
```

Expected: PASS.

- [ ] **Step 3: Run full project tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests -q
```

Expected: PASS. If existing unrelated tests fail, capture exact failure output and verify whether the failing files are outside `src/search_discovery/` and `tests/search_discovery/`.

- [ ] **Step 4: Inspect git status**

Run:

```powershell
git status --short
```

Expected: only files from this plan are staged or modified by the implementer. Existing unrelated dirty files from before this plan may remain, and must not be reverted.

- [ ] **Step 5: Commit README update**

```powershell
git add README.md
git commit -m "docs: document search discovery workflow"
```

---

## Self-Review

Spec coverage:

- Search API first, DailyHot optional only: covered by source registry, source positioning, CLI output paths, and README wording.
- Separate folder: covered by `src/search_discovery/`, `tests/search_discovery/`, `config/search_discovery/`, and `data/search_discovery/`.
- Search source weights: covered by Task 2.
- Keyword categories and query generation: covered by Task 3.
- Detailed content requirement: covered by `SearchResult.has_usable_detail`, provider normalization, enrichment, and discard tests.
- Topic clustering and ranking: covered by Task 5.
- JSON and Markdown outputs: covered by Task 6 and Task 7.
- No overwrite of old project: covered by isolated output paths and CLI test asserting `data/raw/dailyhot_records.json` is not created in a clean temp root.

Placeholder scan:

- No unresolved placeholder markers or unspecified implementation steps are used.
- Each code-writing step includes exact file content or exact code to append.

Type consistency:

- `CreatorProfile`, `SearchResult`, `EnrichedContent`, and `CandidateTopic` are defined in Task 1 and reused consistently.
- `planned_source.source_id`, `source.source_role`, and `profile_source_weights` are defined before CLI use.
- Output file paths match the design document and README section.
