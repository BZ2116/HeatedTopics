# Creator Topic Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an additive creator-oriented topic classification index and Markdown card report from the existing hot-topic pipeline outputs.

**Architecture:** Add a focused classifier module that uses a controlled taxonomy, deterministic matching, bounded keyword extraction, and scoring helpers. Add a renderer for creator cards, then wire both into `src.core_pipeline.run` as `build-creator-topic-index` without changing existing collection commands.

**Tech Stack:** Python 3.10+, dataclasses, standard library JSON/path utilities, existing `pytest` test suite, existing `src.core_pipeline.json_store` helpers.

---

## File Structure

- Create `src/core_pipeline/creator_topic_classifier.py`
  - Owns taxonomy definitions, dataclasses for index records, classification, scoring, keyword extraction, and index construction.
- Modify `src/core_pipeline/report_renderer.py`
  - Add `render_creator_topic_cards(index: dict[str, object]) -> str`.
- Modify `src/core_pipeline/json_store.py`
  - Add `read_jsonl(path)` for compact raw detail input.
- Modify `src/core_pipeline/run.py`
  - Add output paths for creator index/report.
  - Add `build_creator_topic_index_command`.
  - Add CLI command `build-creator-topic-index` and `--render-report`.
- Create `tests/core_pipeline/test_creator_topic_classifier.py`
  - Unit tests for taxonomy matching, alias behavior, keyword limits, scoring, and missing data.
- Modify `tests/core_pipeline/test_report_renderer.py`
  - Add tests for Markdown card rendering.
- Modify `tests/core_pipeline/test_json_store.py`
  - Add `read_jsonl` tests.
- Modify `tests/core_pipeline/test_run.py`
  - Add command wiring tests.

## Scope Check

This plan implements only the classification/indexing layer and a derived Markdown report. It does not implement personalized creator recommendation. The resulting JSON provides recall, ranking, and explanation fields that a future recommendation layer can consume.

---

### Task 1: JSONL Reader

**Files:**
- Modify: `src/core_pipeline/json_store.py`
- Test: `tests/core_pipeline/test_json_store.py`

- [ ] **Step 1: Write failing tests for JSONL reads**

Add these tests to `tests/core_pipeline/test_json_store.py`:

```python
from src.core_pipeline.json_store import read_jsonl


def test_read_jsonl_reads_one_object_per_line():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data" / "records.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"id": "one"}\n{"id": "two"}\n', encoding="utf-8")

        assert read_jsonl(path) == [{"id": "one"}, {"id": "two"}]


def test_read_jsonl_returns_empty_list_for_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "missing.jsonl"

        assert read_jsonl(path) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_json_store.py -q
```

Expected: FAIL because `read_jsonl` is not defined.

- [ ] **Step 3: Implement `read_jsonl`**

Add to `src/core_pipeline/json_store.py`:

```python
def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object on line {line_number} in {file_path}")
            rows.append(data)
    return rows
```

- [ ] **Step 4: Run JSON store tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_json_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/json_store.py tests/core_pipeline/test_json_store.py
git commit -m "feat: read jsonl pipeline inputs"
```

---

### Task 2: Controlled Taxonomy And Classification Types

**Files:**
- Create: `src/core_pipeline/creator_topic_classifier.py`
- Test: `tests/core_pipeline/test_creator_topic_classifier.py`

- [ ] **Step 1: Write failing tests for domain classification and aliases**

Create `tests/core_pipeline/test_creator_topic_classifier.py`:

```python
from src.core_pipeline.creator_topic_classifier import (
    classify_topic,
    extract_keyword_fields,
    normalize_text,
)


def test_classify_gaokao_score_line_uses_deep_domain_path():
    topic = {
        "topic_id": "topic_001",
        "topic_key": "河北高考分数线",
        "canonical_title": "河北高考分数线",
        "platforms": ["weibo"],
        "best_rank": 1,
    }

    result = classify_topic(topic, [], [])

    assert result["domain_path"] == ["教育升学", "高考", "分数线"]
    assert "数据整理" in result["content_modes"]
    assert "学生" in result["audience_tags"]
    assert "家长" in result["audience_tags"]
    assert result["classification_confidence"] == "high"


def test_classify_zhiyuan_guide_keeps_domain_and_mode_separate():
    topic = {
        "topic_id": "topic_002",
        "topic_key": "高考志愿填报指南",
        "canonical_title": "高考志愿填报指南",
        "platforms": ["baidu"],
        "best_rank": 3,
    }

    result = classify_topic(topic, [], [])

    assert result["domain_path"] == ["教育升学", "高考", "志愿填报"]
    assert "经验攻略" in result["content_modes"]
    assert "志愿填报" in result["event_keywords"]


def test_extract_keywords_are_bounded_and_do_not_replace_controlled_tags():
    text = "河北2026高考分数线公布，本科线、物理组443分，志愿填报即将开始。"

    keywords = extract_keyword_fields(text)

    assert len(keywords["entity_keywords"]) <= 12
    assert len(keywords["event_keywords"]) <= 8
    assert len(keywords["match_terms"]) <= 12
    assert "河北" in keywords["entity_keywords"]
    assert "分数线公布" in keywords["event_keywords"]


def test_normalize_text_lowercases_and_removes_extra_whitespace():
    assert normalize_text("  AI   医疗\n应用 ") == "ai医疗应用"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_creator_topic_classifier.py -q
```

Expected: FAIL because `creator_topic_classifier.py` does not exist.

- [ ] **Step 3: Implement taxonomy, text normalization, and `classify_topic`**

Create `src/core_pipeline/creator_topic_classifier.py`:

```python
import re
from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = "1.0"

DOMAIN_RULES = [
    {
        "path": ["教育升学", "高考", "分数线"],
        "terms": ["高考", "分数线", "本科线", "物理组", "历史组"],
        "audience": ["学生", "家长"],
        "modes": ["数据整理", "实时跟进"],
    },
    {
        "path": ["教育升学", "高考", "志愿填报"],
        "terms": ["志愿填报", "报志愿", "专业选择", "院校选择", "填报指南"],
        "audience": ["学生", "家长"],
        "modes": ["经验攻略", "数据整理"],
    },
    {
        "path": ["财经商业", "汽车消费", "新车上市"],
        "terms": ["新车", "上市", "售价", "汽车", "车型"],
        "audience": ["年轻消费群体", "城市居民"],
        "modes": ["数据整理", "观点评论"],
    },
    {
        "path": ["科技AI", "AI应用", "医疗AI"],
        "terms": ["医疗ai", "ai医疗", "医生", "辅助诊断"],
        "audience": ["技术从业者", "泛大众"],
        "modes": ["科普解释", "观点评论"],
    },
    {
        "path": ["社会民生", "公共安全", "案件通报"],
        "terms": ["拘留", "通报", "警方", "案件", "违法"],
        "audience": ["泛大众", "城市居民"],
        "modes": ["实时跟进", "案例复盘"],
    },
]

CONTENT_MODE_ALIASES = {
    "经验攻略": ["攻略", "指南", "教程", "怎么选", "避坑"],
    "数据整理": ["汇总", "名单", "表格", "分数线", "清单"],
    "情绪共鸣": ["破防", "焦虑", "吐槽", "共鸣"],
    "政策解读": ["政策", "规定", "办法", "通知"],
    "实时跟进": ["公布", "发布", "最新", "今日", "刚刚"],
}

EVENT_PATTERNS = {
    "分数线公布": ["分数线公布", "分数线", "本科线"],
    "志愿填报": ["志愿填报", "报志愿"],
    "新车上市": ["新车上市", "上市", "售价"],
    "政策发布": ["政策发布", "规定", "通知"],
    "判决结果": ["判决", "获刑", "处罚"],
}


@dataclass(frozen=True)
class TopicHotness:
    best_rank: int | None
    platforms: list[str]
    hot_values: list[dict[str, str]]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def classify_topic(
    topic: dict[str, Any],
    hot_records: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    title = str(topic.get("canonical_title") or topic.get("title") or topic.get("topic_key") or "")
    topic_key = str(topic.get("topic_key") or title)
    topic_record_ids = {str(record_id) for record_id in topic.get("hot_record_ids", []) if record_id}
    related_records = [record for record in hot_records if str(record.get("id", "")) in topic_record_ids]
    related_details = [
        row for row in detail_rows
        if str(row.get("title", "")) == title or str(row.get("title", "")) == topic_key
    ]
    text = _combined_text(title, related_records, related_details)
    domain_path, domain_terms, confidence = _select_domain_path(text, title)
    content_modes, mode_terms = _select_content_modes(text, domain_path)
    audience_tags = _select_audience_tags(text, domain_path)
    keywords = extract_keyword_fields(text)
    hotness = _topic_hotness(topic, related_records)
    traceability = _traceability(related_details, hotness.platforms)
    freshness = _freshness(text)
    risk_level = _risk_level(text, domain_path)
    creator_fit_score = _creator_fit_score(hotness, traceability, content_modes, confidence, risk_level)
    detail = _detail_text(related_details)
    platforms = hotness.platforms or list(topic.get("platforms", []))
    return {
        "topic_id": str(topic.get("topic_id") or topic_key),
        "topic_key": topic_key,
        "title": title,
        "domain_path": domain_path,
        "secondary_domain_paths": [],
        "content_modes": content_modes,
        "audience_tags": audience_tags,
        "entity_keywords": keywords["entity_keywords"],
        "event_keywords": keywords["event_keywords"],
        "match_terms": keywords["match_terms"],
        "hotness": asdict(hotness),
        "traceability": traceability,
        "freshness": freshness,
        "risk_level": risk_level,
        "creator_fit_score": creator_fit_score,
        "classification_confidence": confidence,
        "match_signals": {
            "domain_terms": domain_terms,
            "content_mode_terms": mode_terms,
            "audience_terms": [tag for tag in audience_tags if tag in text],
        },
        "card": {
            "source_platforms": platforms,
            "summary": _summary(title, domain_path, content_modes),
            "detail": detail,
            "evidence_urls": _evidence_urls(related_details),
        },
    }
```

Continue the same file with these helper functions:

```python
def _combined_text(title: str, records: list[dict[str, Any]], detail_rows: list[dict[str, Any]]) -> str:
    parts = [title]
    parts.extend(str(record.get("title", "")) for record in records)
    parts.extend(str(record.get("desc", "")) for record in records)
    parts.extend(str(row.get("content", ""))[:1000] for row in detail_rows)
    return "\n".join(part for part in parts if part)


def _select_domain_path(text: str, title: str) -> tuple[list[str], list[str], str]:
    normalized_text = normalize_text(text)
    normalized_title = normalize_text(title)
    best_rule = None
    best_score = 0
    best_terms: list[str] = []
    for rule in DOMAIN_RULES:
        score = 0
        terms = []
        for term in rule["terms"]:
            normalized_term = normalize_text(term)
            if normalized_term in normalized_title:
                score += 5
                terms.append(term)
            elif normalized_term in normalized_text:
                score += 2
                terms.append(term)
        if score > best_score:
            best_rule = rule
            best_score = score
            best_terms = terms
    if best_rule is None or best_score < 2:
        return ["未分类", "待人工确认"], [], "low"
    confidence = "high" if best_score >= 5 else "medium"
    return list(best_rule["path"]), best_terms[:5], confidence


def _select_content_modes(text: str, domain_path: list[str]) -> tuple[list[str], list[str]]:
    normalized = normalize_text(text)
    modes: list[str] = []
    terms: list[str] = []
    for rule in DOMAIN_RULES:
        if rule["path"] == domain_path:
            modes.extend(rule["modes"])
    for mode, aliases in CONTENT_MODE_ALIASES.items():
        for alias in aliases:
            if normalize_text(alias) in normalized:
                modes.append(mode)
                terms.append(alias)
                break
    return _unique_limited(modes, 5), _unique_limited(terms, 8)


def _select_audience_tags(text: str, domain_path: list[str]) -> list[str]:
    tags: list[str] = []
    for rule in DOMAIN_RULES:
        if rule["path"] == domain_path:
            tags.extend(rule["audience"])
    normalized = normalize_text(text)
    explicit = {
        "学生": ["学生", "考生"],
        "家长": ["家长", "父母"],
        "打工人": ["上班", "职场", "打工"],
        "投资者": ["投资", "股民"],
        "技术从业者": ["开发者", "程序员", "工程师"],
    }
    for tag, aliases in explicit.items():
        if any(normalize_text(alias) in normalized for alias in aliases):
            tags.append(tag)
    return _unique_limited(tags or ["泛大众"], 3)


def extract_keyword_fields(text: str) -> dict[str, list[str]]:
    entity_candidates = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,12}", text)
    entity_keywords = [
        item for item in entity_candidates
        if item not in {"今日", "最新", "热门", "话题", "详情", "内容"}
    ]
    event_keywords = []
    normalized = normalize_text(text)
    for event, aliases in EVENT_PATTERNS.items():
        if any(normalize_text(alias) in normalized for alias in aliases):
            event_keywords.append(event)
    match_terms = _build_match_terms(entity_keywords, event_keywords)
    return {
        "entity_keywords": _unique_limited(entity_keywords, 12),
        "event_keywords": _unique_limited(event_keywords, 8),
        "match_terms": _unique_limited(match_terms, 12),
    }


def _build_match_terms(entity_keywords: list[str], event_keywords: list[str]) -> list[str]:
    terms: list[str] = []
    for entity in entity_keywords[:6]:
        terms.append(entity)
        for event in event_keywords[:2]:
            terms.append(f"{entity}{event}")
    return terms


def _topic_hotness(topic: dict[str, Any], records: list[dict[str, Any]]) -> TopicHotness:
    platforms = _unique_limited(
        [str(record.get("platform", "")) for record in records if record.get("platform")]
        or [str(platform) for platform in topic.get("platforms", [])],
        10,
    )
    hot_values = [
        {"platform": str(record.get("platform", "")), "value": str(record.get("hot_value", ""))}
        for record in records
        if record.get("platform") and record.get("hot_value") is not None
    ]
    rank = topic.get("best_rank")
    if not isinstance(rank, int):
        ranks = [record.get("rank") for record in records if isinstance(record.get("rank"), int)]
        rank = min(ranks) if ranks else None
    return TopicHotness(best_rank=rank, platforms=platforms, hot_values=hot_values)


def _traceability(detail_rows: list[dict[str, Any]], platforms: list[str]) -> str:
    ok_details = [row for row in detail_rows if str(row.get("content", "")).strip()]
    if len(platforms) >= 2 or len(ok_details) >= 2:
        return "high"
    if ok_details or platforms:
        return "medium"
    return "low"


def _freshness(text: str) -> str:
    normalized = normalize_text(text)
    if any(term in normalized for term in ("刚刚", "今日", "今天", "公布", "发布")):
        return "breaking"
    return "ongoing"


def _risk_level(text: str, domain_path: list[str]) -> str:
    normalized = normalize_text(text)
    high_terms = ["政治", "外交", "涉密"]
    medium_terms = ["违法", "拘留", "医疗", "投资", "未成年", "争议"]
    if any(term in normalized for term in high_terms):
        return "high"
    if any(term in normalized for term in medium_terms) or "案件通报" in domain_path:
        return "medium"
    return "low"


def _creator_fit_score(
    hotness: TopicHotness,
    traceability: str,
    content_modes: list[str],
    confidence: str,
    risk_level: str,
) -> int:
    score = 40
    if hotness.best_rank is not None:
        score += max(0, 25 - min(hotness.best_rank, 25))
    score += {"high": 15, "medium": 8, "low": 0}[traceability]
    score += min(len(content_modes), 5) * 4
    score += {"high": 10, "medium": 5, "low": 0}[confidence]
    score -= {"low": 0, "medium": 8, "high": 20}[risk_level]
    return max(0, min(100, score))


def _detail_text(detail_rows: list[dict[str, Any]]) -> str:
    for row in detail_rows:
        content = str(row.get("content", "")).strip()
        if content:
            return content[:500]
    return "暂无可用详情，已根据热榜标题和元数据生成基础卡片。"


def _evidence_urls(detail_rows: list[dict[str, Any]]) -> list[str]:
    urls = [str(row.get("url", "")) for row in detail_rows if row.get("url")]
    return _unique_limited(urls, 5)


def _summary(title: str, domain_path: list[str], content_modes: list[str]) -> str:
    domain = " > ".join(domain_path)
    modes = "、".join(content_modes) if content_modes else "话题跟进"
    return f"{title} 归入 {domain}，适合做{modes}。"


def _unique_limited(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result
```

- [ ] **Step 4: Run classifier tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_creator_topic_classifier.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/creator_topic_classifier.py tests/core_pipeline/test_creator_topic_classifier.py
git commit -m "feat: classify creator topic metadata"
```

---

### Task 3: Build Full Creator Topic Index

**Files:**
- Modify: `src/core_pipeline/creator_topic_classifier.py`
- Test: `tests/core_pipeline/test_creator_topic_classifier.py`

- [ ] **Step 1: Write failing tests for full index construction**

Append to `tests/core_pipeline/test_creator_topic_classifier.py`:

```python
from src.core_pipeline.creator_topic_classifier import build_creator_topic_index


def test_build_creator_topic_index_adds_schema_and_source_files():
    topics = [
        {
            "topic_id": "topic_001",
            "topic_key": "河北高考分数线",
            "canonical_title": "河北高考分数线",
            "hot_record_ids": ["hot_weibo_001"],
            "platforms": ["weibo"],
            "best_rank": 1,
        }
    ]
    records = [
        {
            "id": "hot_weibo_001",
            "platform": "weibo",
            "title": "河北高考分数线",
            "rank": 1,
            "hot_value": "1784276",
        }
    ]
    details = [
        {
            "source": "weibo",
            "title": "河北高考分数线",
            "content": "河北2026高考分数线公布，本科线、志愿填报成为讨论重点。",
            "url": "https://example.com/weibo",
        }
    ]

    index = build_creator_topic_index(
        topics=topics,
        hot_records=records,
        detail_rows=details,
        generated_at="2026-06-24T16:00:00+08:00",
        source_files=["data/raw/dailyhot_records.json"],
    )

    assert index["schema_version"] == "1.0"
    assert index["generated_at"] == "2026-06-24T16:00:00+08:00"
    assert index["source_files"] == ["data/raw/dailyhot_records.json"]
    assert len(index["topics"]) == 1
    assert index["topics"][0]["hotness"]["hot_values"] == [{"platform": "weibo", "value": "1784276"}]
    assert index["topics"][0]["card"]["evidence_urls"] == ["https://example.com/weibo"]


def test_build_creator_topic_index_handles_missing_inputs():
    index = build_creator_topic_index(
        topics=[],
        hot_records=[],
        detail_rows=[],
        generated_at="2026-06-24T16:00:00+08:00",
        source_files=[],
    )

    assert index["topics"] == []
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_creator_topic_classifier.py -q
```

Expected: FAIL because `build_creator_topic_index` is not defined.

- [ ] **Step 3: Implement `build_creator_topic_index`**

Add to `src/core_pipeline/creator_topic_classifier.py`:

```python
def build_creator_topic_index(
    topics: list[dict[str, Any]],
    hot_records: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    generated_at: str,
    source_files: list[str],
) -> dict[str, Any]:
    topic_records = []
    for index, topic in enumerate(topics, start=1):
        enriched_topic = dict(topic)
        enriched_topic.setdefault("topic_id", f"topic_{index:03d}")
        topic_records.append(classify_topic(enriched_topic, hot_records, detail_rows))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_files": source_files,
        "topics": topic_records,
    }
```

- [ ] **Step 4: Run classifier tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_creator_topic_classifier.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/creator_topic_classifier.py tests/core_pipeline/test_creator_topic_classifier.py
git commit -m "feat: build creator topic index"
```

---

### Task 4: Markdown Card Renderer

**Files:**
- Modify: `src/core_pipeline/report_renderer.py`
- Modify: `tests/core_pipeline/test_report_renderer.py`

- [ ] **Step 1: Write failing renderer test**

Append to `tests/core_pipeline/test_report_renderer.py`:

```python
from src.core_pipeline.report_renderer import render_creator_topic_cards


def test_render_creator_topic_cards_groups_by_domain_and_shows_card_fields():
    index = {
        "generated_at": "2026-06-24T16:00:00+08:00",
        "topics": [
            {
                "title": "河北高考分数线",
                "domain_path": ["教育升学", "高考", "分数线"],
                "content_modes": ["数据整理", "经验攻略"],
                "audience_tags": ["学生", "家长"],
                "entity_keywords": ["河北", "2026高考"],
                "event_keywords": ["分数线公布"],
                "match_terms": ["河北高考分数线"],
                "hotness": {
                    "best_rank": 1,
                    "platforms": ["weibo"],
                    "hot_values": [{"platform": "weibo", "value": "1784276"}],
                },
                "traceability": "high",
                "freshness": "breaking",
                "risk_level": "low",
                "creator_fit_score": 88,
                "card": {
                    "source_platforms": ["weibo"],
                    "summary": "适合做高考数据整理。",
                    "detail": "河北公布 2026 年高考分数线。",
                    "evidence_urls": ["https://example.com/weibo"],
                },
            }
        ],
    }

    markdown = render_creator_topic_cards(index)

    assert "# 创作者热点卡片" in markdown
    assert "## 教育升学" in markdown
    assert "### 河北高考分数线" in markdown
    assert "话题热度" in markdown
    assert "来源平台" in markdown
    assert "可追踪度" in markdown
    assert "河北公布 2026 年高考分数线。" in markdown
```

- [ ] **Step 2: Run renderer test to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_report_renderer.py::test_render_creator_topic_cards_groups_by_domain_and_shows_card_fields -q
```

Expected: FAIL because `render_creator_topic_cards` is not defined.

- [ ] **Step 3: Implement renderer**

Add to `src/core_pipeline/report_renderer.py`:

```python
def render_creator_topic_cards(index: dict[str, object]) -> str:
    topics = [topic for topic in index.get("topics", []) if isinstance(topic, dict)]
    grouped: dict[str, list[dict[str, object]]] = {}
    for topic in topics:
        domain_path = topic.get("domain_path", [])
        domain = "未分类"
        if isinstance(domain_path, list) and domain_path:
            domain = str(domain_path[0])
        grouped.setdefault(domain, []).append(topic)

    lines = [
        "# 创作者热点卡片",
        "",
        f"- 生成时间：`{index.get('generated_at', '')}`",
        f"- 话题数量：`{len(topics)}`",
        "",
    ]
    for domain in sorted(grouped):
        lines.extend([f"## {domain}", ""])
        for topic in grouped[domain]:
            hotness = topic.get("hotness", {}) if isinstance(topic.get("hotness"), dict) else {}
            card = topic.get("card", {}) if isinstance(topic.get("card"), dict) else {}
            hot_values = hotness.get("hot_values", [])
            hot_value_text = _format_hot_values(hot_values if isinstance(hot_values, list) else [])
            lines.extend(
                [
                    f"### {topic.get('title', '未命名话题')}",
                    "",
                    f"- 话题热度：排名 `{hotness.get('best_rank', '')}`；热度 `{hot_value_text}`",
                    f"- 来源平台：`{', '.join(str(item) for item in card.get('source_platforms', hotness.get('platforms', [])))}`",
                    f"- 领域路径：`{' > '.join(str(item) for item in topic.get('domain_path', []))}`",
                    f"- 创作方式：`{', '.join(str(item) for item in topic.get('content_modes', []))}`",
                    f"- 目标受众：`{', '.join(str(item) for item in topic.get('audience_tags', []))}`",
                    f"- 可追踪度：`{topic.get('traceability', '')}`",
                    f"- 新鲜度：`{topic.get('freshness', '')}`",
                    f"- 风险等级：`{topic.get('risk_level', '')}`",
                    f"- 创作者适配分：`{topic.get('creator_fit_score', '')}`",
                    f"- 关键词：`{', '.join(str(item) for item in topic.get('match_terms', []))}`",
                    "",
                    "具体内容：",
                    "",
                    str(card.get("detail", "")),
                    "",
                    "推荐摘要：",
                    "",
                    str(card.get("summary", "")),
                    "",
                ]
            )
            evidence_urls = card.get("evidence_urls", [])
            if isinstance(evidence_urls, list) and evidence_urls:
                lines.append("证据链接：")
                lines.append("")
                lines.extend(f"- {url}" for url in evidence_urls)
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_hot_values(hot_values: list[object]) -> str:
    parts = []
    for row in hot_values:
        if not isinstance(row, dict):
            continue
        platform = str(row.get("platform", "")).strip()
        value = str(row.get("value", "")).strip()
        if platform or value:
            parts.append(f"{platform}:{value}" if platform else value)
    return ", ".join(parts)
```

- [ ] **Step 4: Run renderer tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_report_renderer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/report_renderer.py tests/core_pipeline/test_report_renderer.py
git commit -m "feat: render creator topic cards"
```

---

### Task 5: Command Wiring And File Output

**Files:**
- Modify: `src/core_pipeline/run.py`
- Modify: `tests/core_pipeline/test_run.py`

- [ ] **Step 1: Write failing tests for paths and CLI command**

Add imports in `tests/core_pipeline/test_run.py`:

```python
from src.core_pipeline.run import build_creator_topic_index_command
```

Add tests:

```python
def test_output_paths_include_creator_topic_index_and_report(self):
    paths = output_paths()

    self.assertEqual(paths["creator_topic_index"].as_posix(), "data/processed/creator_topic_index.json")
    self.assertEqual(paths["creator_topic_cards"].as_posix(), "reports/creator_topic_cards.md")


def test_build_creator_topic_index_command_writes_json_and_markdown(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data/raw").mkdir(parents=True)
        (root / "data/evidence").mkdir(parents=True)
        (root / "data/processed").mkdir(parents=True)
        (root / "data/raw/dailyhot_records.json").write_text(
            json.dumps([
                {
                    "id": "hot_weibo_001",
                    "platform": "weibo",
                    "title": "河北高考分数线",
                    "rank": 1,
                    "hot_value": "1784276",
                }
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "data/evidence/detail_evidence_raw.jsonl").write_text(
            json.dumps(
                {
                    "source": "weibo",
                    "title": "河北高考分数线",
                    "content": "河北2026高考分数线公布，本科线、志愿填报成为讨论重点。",
                    "url": "https://example.com/weibo",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "data/processed/topic_clusters.json").write_text(
            json.dumps([
                {
                    "topic_key": "河北高考分数线",
                    "canonical_title": "河北高考分数线",
                    "hot_record_ids": ["hot_weibo_001"],
                    "platforms": ["weibo"],
                    "best_rank": 1,
                }
            ], ensure_ascii=False),
            encoding="utf-8",
        )

        result = build_creator_topic_index_command(
            root=root,
            generated_at="2026-06-24T16:00:00+08:00",
            render_report=True,
        )

        index_path = root / "data/processed/creator_topic_index.json"
        report_path = root / "reports/creator_topic_cards.md"
        self.assertEqual(result["topics_count"], 1)
        self.assertTrue(index_path.exists())
        self.assertTrue(report_path.exists())
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["topics"][0]["domain_path"], ["教育升学", "高考", "分数线"])
        self.assertIn("河北高考分数线", report_path.read_text(encoding="utf-8"))


def test_main_wires_build_creator_topic_index_command(self):
    calls = []

    def fake_command(**kwargs):
        calls.append(kwargs)
        return {"topics_count": 0}

    with patch("sys.argv", ["run.py", "build-creator-topic-index", "--render-report"]):
        with patch("src.core_pipeline.run.build_creator_topic_index_command", fake_command):
            main()

    self.assertEqual(calls[0]["root"], Path("."))
    self.assertTrue(calls[0]["render_report"])
```

- [ ] **Step 2: Run selected tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_run.py -q
```

Expected: FAIL because the command and paths are not wired.

- [ ] **Step 3: Implement command wiring**

Modify imports in `src/core_pipeline/run.py`:

```python
import json

from src.core_pipeline.creator_topic_classifier import build_creator_topic_index
from src.core_pipeline.json_store import read_json_list, read_jsonl, write_json_list, write_jsonl
from src.core_pipeline.report_renderer import (
    render_creator_topic_cards,
    render_markdown_report,
    render_recent_hot_topics_report,
)
```

Add paths to `output_paths()`:

```python
"creator_topic_index": Path("data/processed/creator_topic_index.json"),
"creator_topic_cards": Path("reports/creator_topic_cards.md"),
```

Add command function:

```python
def build_creator_topic_index_command(
    root: Path = Path("."),
    generated_at: str | None = None,
    render_report: bool = False,
) -> dict[str, int]:
    paths = rooted_output_paths(root)
    generated = generated_at or now_shanghai_iso()
    hot_records_path = paths["hot_records"]
    raw_detail_path = paths["raw_detail_evidence"]
    topic_clusters_path = paths["topic_clusters"]
    records = read_json_list(hot_records_path)
    detail_rows = read_jsonl(raw_detail_path)
    topics = read_json_list(topic_clusters_path)
    index = build_creator_topic_index(
        topics=topics,
        hot_records=records,
        detail_rows=detail_rows,
        generated_at=generated,
        source_files=[
            hot_records_path.as_posix(),
            raw_detail_path.as_posix(),
            topic_clusters_path.as_posix(),
        ],
    )
    paths["creator_topic_index"].parent.mkdir(parents=True, exist_ok=True)
    paths["creator_topic_index"].write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if render_report:
        report = render_creator_topic_cards(index)
        paths["creator_topic_cards"].parent.mkdir(parents=True, exist_ok=True)
        paths["creator_topic_cards"].write_text(report, encoding="utf-8")
    return {"topics_count": len(index["topics"])}
```

Update `rooted_output_paths` to include the two new keys automatically because it calls `output_paths()`.

Modify parser choices and flag in `main()`:

```python
parser.add_argument(
    "command",
    choices=(
        "paths",
        "render-report",
        "collect-core-details",
        "collect-recent-details",
        "collect-core-hot-details",
        "build-creator-topic-index",
    ),
)
parser.add_argument("--render-report", action="store_true")
```

Add command branch:

```python
if args.command == "build-creator-topic-index":
    build_creator_topic_index_command(
        root=Path("."),
        render_report=args.render_report,
    )
```

- [ ] **Step 4: Run run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_run.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/run.py tests/core_pipeline/test_run.py
git commit -m "feat: wire creator topic index command"
```

---

### Task 6: End-To-End Verification And Documentation

**Files:**
- Modify: `README.md`
- Test: full relevant suite

- [ ] **Step 1: Add README usage section**

Add a short section to `README.md` near the report/output command documentation:

```markdown
## 创作者热点分类索引

在已有采集结果基础上生成创作者检索推荐用的结构化索引：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run build-creator-topic-index --render-report
```

主要输出：

| 路径 | 内容 |
| --- | --- |
| `data/processed/creator_topic_index.json` | 面向下游检索推荐的结构化话题索引 |
| `reports/creator_topic_cards.md` | 从索引渲染出来的创作者热点卡片报告 |

分类索引采用受控的 `domain_path`、`content_modes`、`audience_tags` 做稳定召回，用 `entity_keywords`、`event_keywords` 和 `match_terms` 做补充检索证据。
```

- [ ] **Step 2: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_json_store.py tests/core_pipeline/test_creator_topic_classifier.py tests/core_pipeline/test_report_renderer.py tests/core_pipeline/test_run.py -q
```

Expected: PASS.

- [ ] **Step 3: Run command against current local data**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run build-creator-topic-index --render-report
```

Expected:

- `data/processed/creator_topic_index.json` is written.
- `reports/creator_topic_cards.md` is written.
- Command exits with code 0.

- [ ] **Step 4: Inspect generated JSON shape**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
@'
import json
from pathlib import Path
index = json.loads(Path("data/processed/creator_topic_index.json").read_text(encoding="utf-8"))
print(index["schema_version"])
print(len(index["topics"]))
print(sorted(index["topics"][0].keys()))
'@ | python -
```

Expected:

- First line: `1.0`
- Second line: a positive integer when local topic data exists.
- Third line includes `domain_path`, `content_modes`, `audience_tags`, `hotness`, `traceability`, and `card`.

- [ ] **Step 5: Run full core pipeline tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add README.md data/processed/creator_topic_index.json reports/creator_topic_cards.md
git add src/core_pipeline tests/core_pipeline
git commit -m "docs: document creator topic index"
```

If generated data and reports are ignored by Git, commit only the README and source/test changes:

```powershell
git add README.md src/core_pipeline tests/core_pipeline
git commit -m "docs: document creator topic index"
```

---

## Self-Review

Spec coverage:

- Structured JSON index: Task 3 and Task 5.
- Markdown report: Task 4 and Task 5.
- Controlled taxonomy: Task 2.
- Flexible keywords with limits: Task 2.
- Traceability, freshness, risk, creator fit score: Task 2.
- Downstream recommendation contract fields: Task 2 and Task 3.
- Error handling for missing inputs: Task 3 and Task 5.
- CLI rollout command: Task 5.
- Tests: Tasks 1 through 6.

Placeholder scan:

- No task uses unspecified placeholders.
- Every code-changing step includes concrete code or exact insertion content.
- Every test step has an exact command and expected outcome.

Type consistency:

- `build_creator_topic_index` returns a dictionary with one `topics` list.
- `build_creator_topic_index_command` writes the index dictionary as the JSON file's top-level object.
- `render_creator_topic_cards` consumes the in-memory `index` dictionary, not the list wrapper used on disk.
