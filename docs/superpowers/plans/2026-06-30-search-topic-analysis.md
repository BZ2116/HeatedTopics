# Search Topic Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional v2 search topic analysis stage that emits human-readable Markdown and machine-readable JSON, with deterministic rule analysis and optional LLM synthesis.

**Architecture:** Add three focused modules under `src/search_discovery`: `analysis.py` for deterministic statistics and topic rows, `model_analysis.py` for OpenAI-compatible model synthesis normalization, and `analysis_render.py` for Markdown output. Wire them into `src/search_discovery/cli.py` behind `--render-analysis` and `--analysis-mode`, leaving existing search discovery behavior unchanged unless the new flag is used.

**Tech Stack:** Python 3.10+, dataclasses already in `types.py`, plain dictionaries for JSON artifacts, pytest, existing `src.core_pipeline.model_topic_summarizer.call_openai_compatible_chat`.

---

## File Structure

- Create `src/search_discovery/analysis.py`
  - Builds `topic_analysis.json` payloads from `CandidateTopic`, `SearchResult`, and `EnrichedContent`.
  - Contains deterministic statistics, priority rules, rule summaries, evidence compaction, and LLM context generation.

- Create `src/search_discovery/model_analysis.py`
  - Builds strict JSON-only model prompts from compact analysis data.
  - Calls an injected `model_call` in tests or the existing OpenAI-compatible helper in CLI.
  - Normalizes successful model output and converts failures into structured `model_error`.

- Create `src/search_discovery/analysis_render.py`
  - Renders `topic_analysis.json` into user-facing Markdown.
  - Prefers model text when available and falls back to rule summaries.

- Modify `src/search_discovery/cli.py`
  - Add `render_analysis`, `analysis_mode`, optional injected `model_call`, and `model_name`.
  - Add output paths for `topic_analysis.json` and `topic_analysis.md`.
  - Write analysis outputs only when `--render-analysis` is passed.

- Modify `README.v2.md`
  - Document `--render-analysis`, `--analysis-mode`, model environment variables, and new output files.

- Create tests:
  - `tests/search_discovery/test_analysis.py`
  - `tests/search_discovery/test_model_analysis.py`
  - `tests/search_discovery/test_analysis_render.py`
  - Extend `tests/search_discovery/test_cli.py`

---

### Task 1: Deterministic Analysis Builder

**Files:**
- Create: `src/search_discovery/analysis.py`
- Test: `tests/search_discovery/test_analysis.py`

- [ ] **Step 1: Write failing tests for statistics, topic rows, and empty input**

Create `tests/search_discovery/test_analysis.py`:

```python
from pathlib import Path

from src.search_discovery.analysis import build_topic_analysis
from src.search_discovery.types import CandidateTopic, EnrichedContent, SearchResult


def _topic(**overrides):
    base = {
        "topic_id": "search_topic_001",
        "title": "AI Agent 工具链",
        "matched_keywords": ["AI Agent", "MCP"],
        "keyword_categories": ["tech_project"],
        "profile_match_score": 80,
        "freshness": "breaking",
        "detail_level": "high",
        "risk_level": "low",
        "source_hits": [
            {
                "source_id": "github_search",
                "title": "agent/repo",
                "url": "https://github.com/agent/repo",
                "content_type": "repo",
                "source_weight": 100,
                "metrics": {"stars": 1200, "recently_recommended": True},
                "recently_recommended": True,
            },
            {
                "source_id": "baidu_qianfan_search",
                "title": "AI Agent 分析",
                "url": "https://example.com/agent",
                "content_type": "web",
                "source_weight": 70,
                "metrics": {},
                "recently_recommended": False,
            },
        ],
        "summary": "AI Agent 工具链在开源项目和中文资料中持续升温。",
        "open_questions": [],
        "created_at": "2026-06-30T10:00:00+08:00",
        "topic_score": 73,
    }
    base.update(overrides)
    return CandidateTopic(**base)


def _result(result_id, source_id, title, content_type="web", risk="ok"):
    return SearchResult(
        result_id=result_id,
        source_id=source_id,
        source_role="primary_search",
        query="AI Agent MCP",
        keyword_category="tech_project",
        title=title,
        url=f"https://example.com/{result_id}",
        snippet=f"{title} 摘要",
        content_type=content_type,
        fetch_status=risk,
        metrics={"recently_recommended": result_id.endswith("1")},
        matched_keywords=["AI Agent"],
    )


def test_build_topic_analysis_counts_statistics_and_topic_features():
    topics = [_topic()]
    results = [
        _result("r1", "github_search", "agent/repo", content_type="repo"),
        _result("r2", "baidu_qianfan_search", "AI Agent 分析", content_type="web"),
    ]
    evidence = [
        EnrichedContent(result_id="r1", url="https://github.com/agent/repo", title="agent/repo", content="开源项目证据", content_quality="high", evidence_confidence="high"),
        EnrichedContent(result_id="r2", url="https://example.com/agent", title="AI Agent 分析", content="中文资料证据", content_quality="medium", evidence_confidence="medium"),
    ]

    analysis = build_topic_analysis(
        profile_path=Path("config/search_discovery/creator_profiles/tech_ai_creator.json"),
        generated_at="2026-06-30T10:00:00+08:00",
        topics=topics,
        results=results,
        evidence=evidence,
    )

    assert analysis["schema_version"] == "0.1"
    assert analysis["statistics"]["total_topics"] == 1
    assert analysis["statistics"]["total_results"] == 2
    assert analysis["statistics"]["total_evidence"] == 2
    assert analysis["statistics"]["source_distribution"] == {"github_search": 1, "baidu_qianfan_search": 1}
    assert analysis["statistics"]["keyword_distribution"] == {"AI Agent": 1, "MCP": 1}
    assert analysis["statistics"]["risk_distribution"] == {"low": 1}
    assert analysis["statistics"]["content_type_distribution"] == {"repo": 1, "web": 1}
    assert analysis["statistics"]["freshness_distribution"] == {"breaking": 1}
    assert analysis["statistics"]["score_buckets"] == {"80_plus": 0, "60_to_79": 1, "40_to_59": 0, "under_40": 0}
    assert analysis["statistics"]["recently_recommended_count"] == 1

    row = analysis["topics"][0]
    assert row["priority"] == "high"
    assert row["evidence_count"] == 2
    assert row["source_ids"] == ["github_search", "baidu_qianfan_search"]
    assert row["content_types"] == ["repo", "web"]
    assert row["rule_summary"]["recommended_format"] == "research_note"
    assert "recently recommended" in " ".join(row["rule_summary"]["verification_notes"])
    assert row["llm_context"]["source_titles"] == ["agent/repo", "AI Agent 分析"]
    assert row["llm_context"]["evidence_bullets"][0].startswith("agent/repo:")


def test_build_topic_analysis_uses_medium_and_low_priorities():
    medium = _topic(topic_id="search_topic_002", topic_score=55, title="中等话题")
    low = _topic(topic_id="search_topic_003", topic_score=30, title="低分话题", risk_level="medium")

    analysis = build_topic_analysis(
        profile_path=Path("profile.json"),
        generated_at="2026-06-30T10:00:00+08:00",
        topics=[medium, low],
        results=[],
        evidence=[],
    )

    assert [topic["priority"] for topic in analysis["topics"]] == ["medium", "low"]
    assert analysis["statistics"]["score_buckets"] == {"80_plus": 0, "60_to_79": 0, "40_to_59": 1, "under_40": 1}


def test_build_topic_analysis_empty_input_is_stable():
    analysis = build_topic_analysis(
        profile_path=Path("profile.json"),
        generated_at="2026-06-30T10:00:00+08:00",
        topics=[],
        results=[],
        evidence=[],
    )

    assert analysis["statistics"]["total_topics"] == 0
    assert analysis["statistics"]["source_distribution"] == {}
    assert analysis["statistics"]["score_buckets"] == {"80_plus": 0, "60_to_79": 0, "40_to_59": 0, "under_40": 0}
    assert analysis["topics"] == []
    assert analysis["model_synthesis"] is None
    assert analysis["model_error"] is None
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/search_discovery/test_analysis.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.search_discovery.analysis'`.

- [ ] **Step 3: Implement deterministic analysis**

Create `src/search_discovery/analysis.py`:

```python
from pathlib import Path
from typing import Any

from src.search_discovery.types import CandidateTopic, EnrichedContent, SearchResult

SCHEMA_VERSION = "0.1"


def build_topic_analysis(
    *,
    profile_path: Path,
    generated_at: str,
    topics: list[CandidateTopic],
    results: list[SearchResult],
    evidence: list[EnrichedContent],
    model_synthesis: dict[str, Any] | None = None,
    model_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topic_rows = [_topic_row(topic, evidence) for topic in topics]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "profile": profile_path.as_posix(),
        "statistics": _statistics(topics, results, evidence),
        "topics": topic_rows,
        "model_synthesis": model_synthesis,
        "model_error": model_error,
    }


def _statistics(
    topics: list[CandidateTopic],
    results: list[SearchResult],
    evidence: list[EnrichedContent],
) -> dict[str, Any]:
    return {
        "total_topics": len(topics),
        "total_results": len(results),
        "total_evidence": len(evidence),
        "source_distribution": _count(result.source_id for result in results if result.fetch_status == "ok"),
        "keyword_distribution": _count(keyword for topic in topics for keyword in topic.matched_keywords),
        "risk_distribution": _count(topic.risk_level for topic in topics),
        "content_type_distribution": _count(_hit_text(hit, "content_type") for topic in topics for hit in topic.source_hits),
        "freshness_distribution": _count(topic.freshness for topic in topics),
        "score_buckets": _score_buckets(topics),
        "recently_recommended_count": sum(
            1
            for topic in topics
            for hit in topic.source_hits
            if bool(hit.get("recently_recommended")) or bool(_hit_metrics(hit).get("recently_recommended"))
        ),
    }


def _topic_row(topic: CandidateTopic, evidence: list[EnrichedContent]) -> dict[str, Any]:
    topic_evidence = _evidence_for_topic(topic, evidence)
    source_ids = _unique(_hit_text(hit, "source_id") for hit in topic.source_hits)
    content_types = _unique(_hit_text(hit, "content_type") for hit in topic.source_hits)
    rule_summary = _rule_summary(topic, topic_evidence)
    return {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "priority": _priority(topic.topic_score),
        "topic_score": topic.topic_score,
        "matched_keywords": topic.matched_keywords,
        "keyword_categories": topic.keyword_categories,
        "freshness": topic.freshness,
        "risk_level": topic.risk_level,
        "detail_level": topic.detail_level,
        "evidence_count": len(topic_evidence),
        "source_ids": source_ids,
        "content_types": content_types,
        "rule_summary": rule_summary,
        "evidence": topic_evidence,
        "llm_context": _llm_context(topic, topic_evidence),
    }


def _evidence_for_topic(topic: CandidateTopic, evidence: list[EnrichedContent]) -> list[dict[str, Any]]:
    urls = {str(hit.get("url", "")).rstrip("/") for hit in topic.source_hits if hit.get("url")}
    titles = {str(hit.get("title", "")).strip() for hit in topic.source_hits if hit.get("title")}
    rows: list[dict[str, Any]] = []
    for item in evidence:
        if item.url.rstrip("/") not in urls and item.title.strip() not in titles:
            continue
        rows.append(
            {
                "result_id": item.result_id,
                "title": item.title,
                "url": item.url,
                "content_excerpt": _truncate(item.content, 220),
                "content_quality": item.content_quality,
                "evidence_confidence": item.evidence_confidence,
                "published_at": item.published_at,
            }
        )
    if rows:
        return rows
    return [
        {
            "result_id": "",
            "title": _hit_text(hit, "title"),
            "url": _hit_text(hit, "url"),
            "content_excerpt": "",
            "content_quality": "low",
            "evidence_confidence": "low",
            "published_at": "",
        }
        for hit in topic.source_hits
    ]


def _rule_summary(topic: CandidateTopic, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "one_line_summary": _truncate(topic.summary, 180),
        "why_it_matters": _why_it_matters(topic),
        "creator_angles": _creator_angles(topic),
        "recommended_format": _recommended_format(topic),
        "verification_notes": _verification_notes(topic, evidence),
    }


def _why_it_matters(topic: CandidateTopic) -> str:
    keyword_text = "、".join(topic.matched_keywords) or "当前关键词"
    source_count = len({str(hit.get("source_id", "")) for hit in topic.source_hits if hit.get("source_id")})
    return f"该话题命中 {keyword_text}，来自 {source_count} 个来源，当前评分 {topic.topic_score}，适合进入选题池继续核验。"


def _creator_angles(topic: CandidateTopic) -> list[str]:
    categories = set(topic.keyword_categories)
    if "tech_project" in categories:
        return ["项目拆解", "工具对比", "实现教程"]
    if "tech_article" in categories:
        return ["教程总结", "实践清单", "架构解释"]
    if "news_trend" in categories:
        return ["时间线梳理", "影响分析", "后续观察"]
    if "product_trend" in categories:
        return ["产品对比", "使用场景分析", "市场解读"]
    return ["趋势观察", "证据汇总", "案例拆解"]


def _recommended_format(topic: CandidateTopic) -> str:
    content_types = {_hit_text(hit, "content_type") for hit in topic.source_hits}
    if topic.risk_level == "high":
        return "research_note"
    if "repo" in content_types:
        return "research_note"
    if topic.risk_level == "medium":
        return "article"
    if topic.freshness == "breaking":
        return "short_post"
    return "article"


def _verification_notes(topic: CandidateTopic, evidence: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    if topic.risk_level == "high":
        notes.append("高风险话题，需要人工核验事实、来源和措辞。")
    elif topic.risk_level == "medium":
        notes.append("中风险话题，建议核验发布时间和关键事实。")
    if len({str(hit.get("source_id", "")) for hit in topic.source_hits if hit.get("source_id")}) <= 1:
        notes.append("single-source: 目前主要来自单一来源，发布前建议补充交叉证据。")
    if any(bool(hit.get("recently_recommended")) or bool(_hit_metrics(hit).get("recently_recommended")) for hit in topic.source_hits):
        notes.append("recently recommended: 该话题近期推荐过，注意避免重复选题。")
    if not any(row.get("published_at") for row in evidence):
        notes.append("缺少明确发布时间，建议打开来源页面复核时效性。")
    return notes or ["低风险，但不要把单一来源扩大为行业共识。"]


def _llm_context(topic: CandidateTopic, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "compact_summary": _truncate(topic.summary, 320),
        "evidence_bullets": [
            f"{row.get('title', '')}: {_truncate(str(row.get('content_excerpt', '')), 160)}"
            for row in evidence[:5]
        ],
        "source_titles": [_hit_text(hit, "title") for hit in topic.source_hits if _hit_text(hit, "title")],
        "metrics": {
            "topic_score": topic.topic_score,
            "profile_match_score": topic.profile_match_score,
            "source_count": len(topic.source_hits),
        },
        "risk_flags": _verification_notes(topic, evidence),
    }


def _priority(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _score_buckets(topics: list[CandidateTopic]) -> dict[str, int]:
    buckets = {"80_plus": 0, "60_to_79": 0, "40_to_59": 0, "under_40": 0}
    for topic in topics:
        if topic.topic_score >= 80:
            buckets["80_plus"] += 1
        elif topic.topic_score >= 60:
            buckets["60_to_79"] += 1
        elif topic.topic_score >= 40:
            buckets["40_to_59"] += 1
        else:
            buckets["under_40"] += 1
    return buckets


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _unique(values) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _hit_text(hit: dict[str, Any], key: str) -> str:
    return str(hit.get(key, "") or "").strip()


def _hit_metrics(hit: dict[str, Any]) -> dict[str, Any]:
    metrics = hit.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
```

- [ ] **Step 4: Run analysis tests**

Run:

```powershell
uv run pytest tests/search_discovery/test_analysis.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add src/search_discovery/analysis.py tests/search_discovery/test_analysis.py
git commit -m "Add deterministic search topic analysis"
```

---

### Task 2: Optional Model Analysis

**Files:**
- Create: `src/search_discovery/model_analysis.py`
- Test: `tests/search_discovery/test_model_analysis.py`

- [ ] **Step 1: Write failing tests for model prompt, normalization, partial output, and failures**

Create `tests/search_discovery/test_model_analysis.py`:

```python
from src.search_discovery.model_analysis import build_model_topic_analysis


def _analysis():
    return {
        "schema_version": "0.1",
        "generated_at": "2026-06-30T10:00:00+08:00",
        "statistics": {"total_topics": 2, "source_distribution": {"github_search": 1}},
        "topics": [
            {
                "topic_id": "search_topic_001",
                "title": "AI Agent 工具链",
                "priority": "high",
                "topic_score": 73,
                "risk_level": "low",
                "matched_keywords": ["AI Agent"],
                "rule_summary": {"one_line_summary": "规则摘要"},
                "llm_context": {
                    "compact_summary": "规则摘要",
                    "evidence_bullets": ["证据一"],
                    "source_titles": ["agent/repo"],
                    "risk_flags": ["低风险"],
                },
            },
            {
                "topic_id": "search_topic_002",
                "title": "MCP 安全",
                "priority": "medium",
                "topic_score": 55,
                "risk_level": "medium",
                "matched_keywords": ["MCP"],
                "rule_summary": {"one_line_summary": "规则摘要二"},
                "llm_context": {
                    "compact_summary": "规则摘要二",
                    "evidence_bullets": ["证据二"],
                    "source_titles": ["security"],
                    "risk_flags": ["中风险"],
                },
            },
        ],
    }


def test_build_model_topic_analysis_normalizes_valid_output():
    captured = {}

    def fake_model_call(messages):
        captured["messages"] = messages
        return {
            "overall_summary": {
                "core_conclusion": "核心结论",
                "topic_landscape": "话题格局",
                "creator_strategy": "创作者策略",
                "risk_and_verification": "核验提示",
            },
            "topic_suggestions": {
                "search_topic_001": {
                    "one_line_summary": "模型摘要",
                    "why_it_matters": "值得做",
                    "creator_angles": ["项目拆解", "工具对比"],
                    "recommended_format": "article",
                    "verification_notes": ["核验来源"],
                }
            },
        }

    result = build_model_topic_analysis(
        analysis=_analysis(),
        model_call=fake_model_call,
        model="gpt-test",
        generated_at="2026-06-30T10:00:00+08:00",
        max_topics=1,
    )

    assert result["mode"] == "model"
    assert result["model"] == "gpt-test"
    assert result["overall_summary"]["core_conclusion"] == "核心结论"
    assert result["topic_suggestions"]["search_topic_001"]["creator_angles"] == ["项目拆解", "工具对比"]
    assert "search_topic_002" not in captured["messages"][1]["content"]


def test_build_model_topic_analysis_normalizes_missing_fields():
    def fake_model_call(messages):
        return {"overall_summary": {}, "topic_suggestions": {"search_topic_001": {"creator_angles": "not-list"}}}

    result = build_model_topic_analysis(
        analysis=_analysis(),
        model_call=fake_model_call,
        model="gpt-test",
        generated_at="2026-06-30T10:00:00+08:00",
    )

    suggestion = result["topic_suggestions"]["search_topic_001"]
    assert result["overall_summary"]["creator_strategy"] == ""
    assert suggestion["one_line_summary"] == ""
    assert suggestion["creator_angles"] == []
    assert suggestion["verification_notes"] == []


def test_build_model_topic_analysis_returns_error_when_model_raises():
    def fake_model_call(messages):
        raise RuntimeError("missing key")

    result = build_model_topic_analysis(
        analysis=_analysis(),
        model_call=fake_model_call,
        model="gpt-test",
        generated_at="2026-06-30T10:00:00+08:00",
    )

    assert result["error_type"] == "RuntimeError"
    assert "missing key" in result["message"]
    assert result["mode"] == "model_error"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/search_discovery/test_model_analysis.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.search_discovery.model_analysis'`.

- [ ] **Step 3: Implement model analysis**

Create `src/search_discovery/model_analysis.py`:

```python
import json
from typing import Any, Callable

ModelCall = Callable[[list[dict[str, str]]], dict[str, Any]]


def build_model_topic_analysis(
    *,
    analysis: dict[str, Any],
    model_call: ModelCall,
    model: str,
    generated_at: str,
    max_topics: int = 12,
) -> dict[str, Any]:
    compact = _compact_analysis(analysis, max_topics=max_topics)
    messages = _messages(compact)
    try:
        raw = model_call(messages)
    except Exception as exc:
        return {
            "mode": "model_error",
            "generated_at": generated_at,
            "model": model,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    if not isinstance(raw, dict):
        return {
            "mode": "model_error",
            "generated_at": generated_at,
            "model": model,
            "error_type": "invalid_model_json",
            "message": "Model response must be a JSON object.",
        }
    return _normalize(raw, generated_at=generated_at, model=model)


def _compact_analysis(analysis: dict[str, Any], max_topics: int) -> dict[str, Any]:
    topics = [topic for topic in analysis.get("topics", []) if isinstance(topic, dict)]
    return {
        "statistics": analysis.get("statistics", {}),
        "topics": [_compact_topic(topic) for topic in topics[:max_topics]],
    }


def _compact_topic(topic: dict[str, Any]) -> dict[str, Any]:
    context = topic.get("llm_context") if isinstance(topic.get("llm_context"), dict) else {}
    rule_summary = topic.get("rule_summary") if isinstance(topic.get("rule_summary"), dict) else {}
    return {
        "topic_id": _text(topic.get("topic_id")),
        "title": _text(topic.get("title")),
        "priority": _text(topic.get("priority")),
        "topic_score": topic.get("topic_score", 0),
        "risk_level": _text(topic.get("risk_level")),
        "matched_keywords": _string_list(topic.get("matched_keywords"), 8),
        "rule_summary": {
            "one_line_summary": _text(rule_summary.get("one_line_summary")),
            "why_it_matters": _text(rule_summary.get("why_it_matters")),
            "creator_angles": _string_list(rule_summary.get("creator_angles"), 8),
            "verification_notes": _string_list(rule_summary.get("verification_notes"), 8),
        },
        "llm_context": {
            "compact_summary": _truncate(_text(context.get("compact_summary")), 500),
            "evidence_bullets": [_truncate(item, 260) for item in _string_list(context.get("evidence_bullets"), 5)],
            "source_titles": _string_list(context.get("source_titles"), 6),
            "risk_flags": _string_list(context.get("risk_flags"), 6),
        },
    }


def _messages(compact: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是严谨的中文选题分析助手。你只能根据输入的结构化搜索证据进行归纳，"
        "不要编造事实。只输出 JSON 对象，不要输出 Markdown。"
    )
    payload = {
        "task": "归纳本轮搜索发现的话题，并为每个 topic_id 给出面向创作者的建议。",
        "requirements": [
            "overall_summary 必须包含 core_conclusion、topic_landscape、creator_strategy、risk_and_verification。",
            "topic_suggestions 的 key 必须使用输入里的 topic_id。",
            "每个 topic suggestion 必须包含 one_line_summary、why_it_matters、creator_angles、recommended_format、verification_notes。",
            "没有证据的信息要写不确定，不能猜测事实。",
        ],
        "output_schema": {
            "overall_summary": {
                "core_conclusion": "string",
                "topic_landscape": "string",
                "creator_strategy": "string",
                "risk_and_verification": "string",
            },
            "topic_suggestions": {
                "topic_id": {
                    "one_line_summary": "string",
                    "why_it_matters": "string",
                    "creator_angles": ["string"],
                    "recommended_format": "string",
                    "verification_notes": ["string"],
                }
            },
        },
        "analysis": compact,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _normalize(raw: dict[str, Any], *, generated_at: str, model: str) -> dict[str, Any]:
    overall = raw.get("overall_summary") if isinstance(raw.get("overall_summary"), dict) else {}
    suggestions = raw.get("topic_suggestions") if isinstance(raw.get("topic_suggestions"), dict) else {}
    return {
        "mode": "model",
        "model": model,
        "generated_at": generated_at,
        "overall_summary": {
            "core_conclusion": _text(overall.get("core_conclusion")),
            "topic_landscape": _text(overall.get("topic_landscape")),
            "creator_strategy": _text(overall.get("creator_strategy")),
            "risk_and_verification": _text(overall.get("risk_and_verification")),
        },
        "topic_suggestions": {
            str(topic_id): _normalize_suggestion(value)
            for topic_id, value in suggestions.items()
            if isinstance(value, dict)
        },
    }


def _normalize_suggestion(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "one_line_summary": _text(value.get("one_line_summary")),
        "why_it_matters": _text(value.get("why_it_matters")),
        "creator_angles": _string_list(value.get("creator_angles"), 8),
        "recommended_format": _text(value.get("recommended_format")),
        "verification_notes": _string_list(value.get("verification_notes"), 8),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
```

- [ ] **Step 4: Run model analysis tests**

Run:

```powershell
uv run pytest tests/search_discovery/test_model_analysis.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add src/search_discovery/model_analysis.py tests/search_discovery/test_model_analysis.py
git commit -m "Add model synthesis for search topic analysis"
```

---

### Task 3: Markdown Renderer

**Files:**
- Create: `src/search_discovery/analysis_render.py`
- Test: `tests/search_discovery/test_analysis_render.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/search_discovery/test_analysis_render.py`:

```python
from src.search_discovery.analysis_render import render_topic_analysis_markdown


def _analysis(model=False):
    payload = {
        "generated_at": "2026-06-30T10:00:00+08:00",
        "statistics": {
            "total_topics": 1,
            "total_results": 2,
            "total_evidence": 2,
            "source_distribution": {"github_search": 1},
            "keyword_distribution": {"AI Agent": 1},
            "risk_distribution": {"low": 1},
            "content_type_distribution": {"repo": 1},
            "freshness_distribution": {"breaking": 1},
            "score_buckets": {"80_plus": 0, "60_to_79": 1, "40_to_59": 0, "under_40": 0},
            "recently_recommended_count": 0,
        },
        "topics": [
            {
                "topic_id": "search_topic_001",
                "title": "AI Agent 工具链",
                "priority": "high",
                "topic_score": 73,
                "risk_level": "low",
                "rule_summary": {
                    "one_line_summary": "规则摘要",
                    "why_it_matters": "规则说明",
                    "creator_angles": ["项目拆解"],
                    "recommended_format": "research_note",
                    "verification_notes": ["核验规则"],
                },
                "evidence": [
                    {"title": "agent/repo", "url": "https://github.com/agent/repo", "content_excerpt": "证据"}
                ],
            }
        ],
        "model_synthesis": None,
        "model_error": None,
    }
    if model:
        payload["model_synthesis"] = {
            "overall_summary": {
                "core_conclusion": "模型总判断",
                "topic_landscape": "模型格局",
                "creator_strategy": "模型策略",
                "risk_and_verification": "模型核验",
            },
            "topic_suggestions": {
                "search_topic_001": {
                    "one_line_summary": "模型摘要",
                    "why_it_matters": "模型价值",
                    "creator_angles": ["模型角度"],
                    "recommended_format": "article",
                    "verification_notes": ["模型核验点"],
                }
            },
        }
    return payload


def test_render_topic_analysis_markdown_uses_rule_fallback():
    markdown = render_topic_analysis_markdown(_analysis())

    assert "# 选题分析报告" in markdown
    assert "## 本轮概览" in markdown
    assert "共 1 个候选话题" in markdown
    assert "规则摘要" in markdown
    assert "项目拆解" in markdown
    assert "[agent/repo](https://github.com/agent/repo)" in markdown
    assert "## 统计附录" in markdown


def test_render_topic_analysis_markdown_prefers_model_text():
    markdown = render_topic_analysis_markdown(_analysis(model=True))

    assert "模型总判断" in markdown
    assert "模型摘要" in markdown
    assert "模型角度" in markdown
    assert "模型核验点" in markdown
    assert "规则摘要" not in markdown


def test_render_topic_analysis_markdown_handles_empty_topics():
    markdown = render_topic_analysis_markdown(
        {
            "generated_at": "2026-06-30T10:00:00+08:00",
            "statistics": {"total_topics": 0, "total_results": 0, "total_evidence": 0},
            "topics": [],
            "model_synthesis": None,
            "model_error": None,
        }
    )

    assert "No usable search topics were found." in markdown
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/search_discovery/test_analysis_render.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.search_discovery.analysis_render'`.

- [ ] **Step 3: Implement renderer**

Create `src/search_discovery/analysis_render.py`:

```python
from typing import Any


def render_topic_analysis_markdown(analysis: dict[str, Any]) -> str:
    generated_at = str(analysis.get("generated_at", ""))
    stats = analysis.get("statistics") if isinstance(analysis.get("statistics"), dict) else {}
    topics = [topic for topic in analysis.get("topics", []) if isinstance(topic, dict)]
    lines = [
        "# 选题分析报告",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## 本轮概览",
        "",
        f"- 共 {stats.get('total_topics', 0)} 个候选话题，{stats.get('total_results', 0)} 条搜索结果，{stats.get('total_evidence', 0)} 条证据。",
        f"- 近期重复推荐：{stats.get('recently_recommended_count', 0)} 个来源命中。",
        "",
    ]
    if not topics:
        lines.extend(["No usable search topics were found.", ""])
        return "\n".join(lines)

    lines.extend(_summary_section(analysis))
    lines.extend(["## Top 选题", ""])
    for index, topic in enumerate(topics[:10], start=1):
        suggestion = _topic_suggestion(analysis, topic)
        lines.extend(
            [
                f"### {index}. {topic.get('title', '')}",
                "",
                f"- 推荐级别：{topic.get('priority', '')} / {topic.get('topic_score', 0)}",
                f"- 摘要：{suggestion.get('one_line_summary', '')}",
                f"- 为什么值得做：{suggestion.get('why_it_matters', '')}",
                f"- 推荐形式：{suggestion.get('recommended_format', '')}",
                f"- 创作角度：{', '.join(_string_list(suggestion.get('creator_angles')))}",
                f"- 风险和核验：{'; '.join(_string_list(suggestion.get('verification_notes')))}",
                "- 证据来源：",
            ]
        )
        for evidence in _evidence_rows(topic):
            title = str(evidence.get("title", "untitled"))
            url = str(evidence.get("url", ""))
            if url:
                lines.append(f"  - [{title}]({url})")
            else:
                lines.append(f"  - {title}")
        lines.append("")

    lines.extend(_statistics_appendix(stats))
    return "\n".join(lines)


def _summary_section(analysis: dict[str, Any]) -> list[str]:
    synthesis = analysis.get("model_synthesis") if isinstance(analysis.get("model_synthesis"), dict) else {}
    overall = synthesis.get("overall_summary") if isinstance(synthesis.get("overall_summary"), dict) else {}
    if overall:
        return [
            "## 归纳总结",
            "",
            f"- 核心结论：{overall.get('core_conclusion', '')}",
            f"- 话题格局：{overall.get('topic_landscape', '')}",
            f"- 创作者策略：{overall.get('creator_strategy', '')}",
            f"- 风险核验：{overall.get('risk_and_verification', '')}",
            "",
        ]
    stats = analysis.get("statistics") if isinstance(analysis.get("statistics"), dict) else {}
    return [
        "## 归纳总结",
        "",
        f"- 本轮主要从 {', '.join((stats.get('source_distribution') or {}).keys()) or '已配置来源'} 收集候选话题。",
        "- 当前为规则归纳结果，适合先做选题筛选，再人工核验关键事实。",
        "",
    ]


def _topic_suggestion(analysis: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    topic_id = str(topic.get("topic_id", ""))
    synthesis = analysis.get("model_synthesis") if isinstance(analysis.get("model_synthesis"), dict) else {}
    suggestions = synthesis.get("topic_suggestions") if isinstance(synthesis.get("topic_suggestions"), dict) else {}
    model_suggestion = suggestions.get(topic_id)
    if isinstance(model_suggestion, dict) and any(str(value or "").strip() for value in model_suggestion.values() if not isinstance(value, list)):
        return model_suggestion
    rule = topic.get("rule_summary")
    return rule if isinstance(rule, dict) else {}


def _evidence_rows(topic: dict[str, Any]) -> list[dict[str, Any]]:
    rows = topic.get("evidence")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _statistics_appendix(stats: dict[str, Any]) -> list[str]:
    lines = ["## 统计附录", ""]
    for title, key in (
        ("来源分布", "source_distribution"),
        ("关键词分布", "keyword_distribution"),
        ("内容类型", "content_type_distribution"),
        ("风险分布", "risk_distribution"),
        ("时效分布", "freshness_distribution"),
        ("分数区间", "score_buckets"),
    ):
        lines.extend([f"### {title}", ""])
        values = stats.get(key) if isinstance(stats.get(key), dict) else {}
        if not values:
            lines.extend(["- 无", ""])
            continue
        for name, count in values.items():
            lines.append(f"- `{name}`: {count}")
        lines.append("")
    return lines


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
```

- [ ] **Step 4: Run renderer tests**

Run:

```powershell
uv run pytest tests/search_discovery/test_analysis_render.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add src/search_discovery/analysis_render.py tests/search_discovery/test_analysis_render.py
git commit -m "Render search topic analysis report"
```

---

### Task 4: CLI Integration

**Files:**
- Modify: `src/search_discovery/cli.py`
- Test: `tests/search_discovery/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Append these tests to `tests/search_discovery/test_cli.py`:

```python
def test_run_discovery_command_writes_rule_analysis(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "custom_keywords": ["AI Agent", "MCP"],
            }
        ),
        encoding="utf-8",
    )

    class Provider:
        source_id = "github_search"

        def search_rows(self, query, **kwargs):
            return [
                {
                    "result_id": "github_search_001",
                    "title": "agent/repo",
                    "url": "https://github.com/agent/repo",
                    "snippet": "AI Agent MCP repo",
                    "content_type": "repo",
                    "metrics": {"stars": 1000},
                    "fetch_status": "ok",
                }
            ]

    monkeypatch.setattr("src.search_discovery.cli._build_registry", lambda: SearchProviderRegistry([Provider()]))
    monkeypatch.setattr("src.search_discovery.cli.build_search_routes", lambda profile: [
        SearchRoute(
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent MCP",
            intent="tech_project",
            weight=100,
            reason="test route",
        )
    ])

    counts = run_discovery_command(
        root=tmp_path,
        profile_path=profile_path,
        render_report=False,
        render_analysis=True,
        analysis_mode="rule",
    )

    analysis_path = tmp_path / "data/search_discovery/processed/topic_analysis.json"
    report_path = tmp_path / "reports/search_discovery/topic_analysis.md"
    assert counts["analysis_topics_count"] == 1
    assert analysis_path.exists()
    assert report_path.exists()
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert analysis["statistics"]["total_topics"] == 1
    assert analysis["model_synthesis"] is None
    assert "选题分析报告" in report_path.read_text(encoding="utf-8")


def test_run_discovery_command_writes_model_analysis(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"creator_id": "creator_001", "role": "科技类博主", "profile_type": "tech_ai_creator", "custom_keywords": ["AI Agent"]}),
        encoding="utf-8",
    )

    class Provider:
        source_id = "github_search"

        def search_rows(self, query, **kwargs):
            return [{"title": "agent/repo", "url": "https://github.com/agent/repo", "snippet": "AI Agent repo", "content_type": "repo"}]

    def fake_model_call(messages):
        return {
            "overall_summary": {"core_conclusion": "模型结论"},
            "topic_suggestions": {"search_topic_001": {"one_line_summary": "模型摘要", "creator_angles": ["模型角度"]}},
        }

    monkeypatch.setattr("src.search_discovery.cli._build_registry", lambda: SearchProviderRegistry([Provider()]))
    monkeypatch.setattr("src.search_discovery.cli.build_search_routes", lambda profile: [
        SearchRoute("github_search", "vertical_project", "AI Agent", "tech_project", 100, "test route")
    ])

    run_discovery_command(
        root=tmp_path,
        profile_path=profile_path,
        render_report=False,
        render_analysis=True,
        analysis_mode="model",
        model_call=fake_model_call,
        model_name="gpt-test",
    )

    analysis = json.loads((tmp_path / "data/search_discovery/processed/topic_analysis.json").read_text(encoding="utf-8"))
    assert analysis["model_synthesis"]["overall_summary"]["core_conclusion"] == "模型结论"
    assert "模型摘要" in (tmp_path / "reports/search_discovery/topic_analysis.md").read_text(encoding="utf-8")
```

If `SearchProviderRegistry` or `SearchRoute` is not imported at the top of `tests/search_discovery/test_cli.py`, add:

```python
from src.search_discovery.providers import SearchProviderRegistry
from src.search_discovery.types import SearchRoute
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```powershell
uv run pytest tests/search_discovery/test_cli.py -q
```

Expected: fail because `run_discovery_command()` does not accept `render_analysis`, `analysis_mode`, `model_call`, or `model_name`.

- [ ] **Step 3: Modify CLI imports and function signature**

In `src/search_discovery/cli.py`, add imports:

```python
import os
from collections.abc import Callable
from typing import Any

from src.core_pipeline.model_topic_summarizer import DEFAULT_MODEL, call_openai_compatible_chat
from src.search_discovery.analysis import build_topic_analysis
from src.search_discovery.analysis_render import render_topic_analysis_markdown
from src.search_discovery.model_analysis import build_model_topic_analysis
```

Change the signature:

```python
def run_discovery_command(
    root: Path,
    profile_path: Path,
    render_report: bool = False,
    render_analysis: bool = False,
    analysis_mode: str = "rule",
    model_call: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
    model_name: str | None = None,
) -> dict[str, int]:
```

- [ ] **Step 4: Add analysis output paths**

Extend `_output_paths(root)`:

```python
"topic_analysis": root / "data/search_discovery/processed/topic_analysis.json",
"analysis_report": root / "reports/search_discovery/topic_analysis.md",
```

- [ ] **Step 5: Write analysis files inside `run_discovery_command`**

After the existing `if render_report:` block and before `updated_history = ...`, add:

```python
    analysis_topics_count = 0
    if render_analysis:
        model = model_name or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
        analysis = build_topic_analysis(
            profile_path=profile_path,
            generated_at=generated_at,
            topics=topics,
            results=results,
            evidence=enriched,
        )
        if analysis_mode == "model":
            call = model_call or (lambda messages: call_openai_compatible_chat(messages, model=model))
            model_result = build_model_topic_analysis(
                analysis=analysis,
                model_call=call,
                model=model,
                generated_at=generated_at,
            )
            if model_result.get("mode") == "model_error":
                analysis = build_topic_analysis(
                    profile_path=profile_path,
                    generated_at=generated_at,
                    topics=topics,
                    results=results,
                    evidence=enriched,
                    model_error=model_result,
                )
            else:
                analysis = build_topic_analysis(
                    profile_path=profile_path,
                    generated_at=generated_at,
                    topics=topics,
                    results=results,
                    evidence=enriched,
                    model_synthesis=model_result,
                )
        write_json(paths["topic_analysis"], analysis)
        paths["analysis_report"].parent.mkdir(parents=True, exist_ok=True)
        paths["analysis_report"].write_text(render_topic_analysis_markdown(analysis), encoding="utf-8")
        analysis_topics_count = len(analysis["topics"])
```

Then include the count in the returned dict:

```python
        "analysis_topics_count": analysis_topics_count,
```

- [ ] **Step 6: Add CLI arguments**

In `main()` add:

```python
    parser.add_argument("--render-analysis", action="store_true")
    parser.add_argument("--analysis-mode", choices=("rule", "model"), default="rule")
```

Pass them into `run_discovery_command`:

```python
    counts = run_discovery_command(
        Path("."),
        Path(args.profile),
        render_report=args.render_report,
        render_analysis=args.render_analysis,
        analysis_mode=args.analysis_mode,
    )
```

- [ ] **Step 7: Run CLI tests**

Run:

```powershell
uv run pytest tests/search_discovery/test_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 8: Commit Task 4**

Run:

```powershell
git add src/search_discovery/cli.py tests/search_discovery/test_cli.py
git commit -m "Wire search topic analysis into CLI"
```

---

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.v2.md`
- Optional if needed: `.env.example`

- [ ] **Step 1: Update README.v2.md analysis usage**

Add a short section near the output/report usage section:

```markdown
## 选题分析输出

如果希望在搜索推荐之外生成更完整的整理、归纳和统计结果，开启 `--render-analysis`：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-analysis `
  --analysis-mode rule
```

输出文件：

| 路径 | 用途 |
| --- | --- |
| `data/search_discovery/processed/topic_analysis.json` | 面向程序和大语言模型的结构化统计、证据和话题上下文 |
| `reports/search_discovery/topic_analysis.md` | 面向用户的选题分析报告 |

`--analysis-mode rule` 不需要模型 key。`--analysis-mode model` 会调用 OpenAI-compatible Chat API，为总体归纳和每个话题生成建议：

```text
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

模型调用失败时，流程仍会输出规则版分析，并在 `topic_analysis.json` 的 `model_error` 字段记录原因。
```

- [ ] **Step 2: Run focused tests**

Run:

```powershell
uv run pytest tests/search_discovery/test_analysis.py tests/search_discovery/test_model_analysis.py tests/search_discovery/test_analysis_render.py tests/search_discovery/test_cli.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run full search discovery tests**

Run:

```powershell
uv run pytest tests/search_discovery -q
```

Expected: all search discovery tests pass.

- [ ] **Step 4: Run rule-mode CLI smoke test**

Run:

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-analysis `
  --analysis-mode rule
```

Expected: command exits `0` and prints JSON including positive `search_results_count`, `evidence_count`, `topics_count`, and `analysis_topics_count`. Confirm these files exist:

```text
data/search_discovery/processed/topic_analysis.json
reports/search_discovery/topic_analysis.md
```

- [ ] **Step 5: Optionally run model-mode smoke test when model credentials exist**

Run only if `OPENAI_API_KEY` is configured:

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-analysis `
  --analysis-mode model
```

Expected: command exits `0`. If the model call succeeds, `topic_analysis.json` has `model_synthesis.mode == "model"`. If the model call fails, `topic_analysis.json` has `model_error.mode == "model_error"` and the Markdown report still exists.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add README.v2.md
git commit -m "Document search topic analysis output"
```

---

## Final Verification

After all tasks are complete, run:

```powershell
uv run pytest tests/search_discovery -q
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-report `
  --render-analysis `
  --analysis-mode rule
git status --short
```

Expected:

- All `tests/search_discovery` tests pass.
- CLI exits `0`.
- Existing outputs still exist:
  - `data/search_discovery/raw/search_results.jsonl`
  - `data/search_discovery/evidence/search_content_evidence.jsonl`
  - `data/search_discovery/processed/search_topic_index.json`
  - `reports/search_discovery/search_topic_recommendations.md`
- New outputs exist:
  - `data/search_discovery/processed/topic_analysis.json`
  - `reports/search_discovery/topic_analysis.md`
- `git status --short` contains only expected ignored/untracked runtime outputs, such as `?? data/`, unless the user wants generated artifacts committed.

## Spec Coverage Review

- Human-facing Markdown report: Task 3 and Task 4.
- Machine-facing JSON artifact: Task 1 and Task 4.
- Deterministic statistics: Task 1.
- Optional model synthesis: Task 2 and Task 4.
- Soft failure for model issues: Task 2 and Task 4.
- CLI flags: Task 4.
- Documentation: Task 5.
- Verification commands: Task 5 and Final Verification.
