# Topic Card Cleaning And Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve creator topic cards by adding deterministic content cleaning, structured summaries, summary priority, and a creator-facing Markdown layout.

**Architecture:** Add two focused modules: `topic_content_cleaner.py` for local deterministic cleanup and `topic_summary.py` for rule/manual/model-summary selection. Keep `creator_topic_classifier.py` responsible for assembling the topic index, but delegate cleaning and summary fields to the new modules; keep model summary integration optional and non-blocking.

**Tech Stack:** Python 3.10+, dataclasses, standard library JSON/path utilities, existing `pytest` tests, existing `src.core_pipeline.run` command wiring.

---

## File Structure

- Create `src/core_pipeline/topic_content_cleaner.py`
  - Owns `CleanedContent` and deterministic cleanup of raw detail text into `raw_content_preview` and `clean_content`.
- Create `tests/core_pipeline/test_topic_content_cleaner.py`
  - Tests page chrome removal, sidebar noise reduction, whitespace cleanup, and fallback behavior.
- Create `src/core_pipeline/topic_summary.py`
  - Owns rule summary generation, manual summary loading, summary normalization, and display-summary priority.
- Create `tests/core_pipeline/test_topic_summary.py`
  - Tests rule summaries, manual override, model override, and malformed manual JSON fallback.
- Modify `src/core_pipeline/creator_topic_classifier.py`
  - Use cleaner and summary generator when building `card`.
  - Add `manual_summaries` and `model_summaries` parameters to `classify_topic` and `build_creator_topic_index`.
- Modify `tests/core_pipeline/test_creator_topic_classifier.py`
  - Assert new `card` shape and fallback summary fields.
- Modify `src/core_pipeline/report_renderer.py`
  - Render creator cards from structured summary fields and `clean_content`.
- Modify `tests/core_pipeline/test_report_renderer.py`
  - Assert new creator-facing Markdown layout.
- Modify `src/core_pipeline/run.py`
  - Add optional `--manual-summaries` path and `--summary-mode` flag.
  - Load manual summaries when provided.
- Modify `tests/core_pipeline/test_run.py`
  - Assert command wires manual summary path and leaves model mode non-blocking.

## Scope Check

This plan implements deterministic cleaning, rule summaries, manual-summary overrides, and renderer changes. It reserves model summaries behind a shape-compatible `model_summaries` input and `--summary-mode model` flag, but it does not call an external API in this iteration. That keeps the immediate card quality work testable and independent from API credentials/cost.

---

### Task 1: Deterministic Content Cleaner

**Files:**
- Create: `src/core_pipeline/topic_content_cleaner.py`
- Create: `tests/core_pipeline/test_topic_content_cleaner.py`

- [ ] **Step 1: Write failing cleaner tests**

Create `tests/core_pipeline/test_topic_content_cleaner.py`:

```python
from src.core_pipeline.topic_content_cleaner import clean_topic_content


def test_clean_topic_content_removes_common_page_chrome():
    raw = """
    NEW
    1
    搜索结果
    综合
    智搜
    实时
    用户
    视频
    图片
    话题
    高级搜索
    热门
    c
    央视新闻 今天15:00 来自 微博网页版
    河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。
    展开c
    下一页
    """

    cleaned = clean_topic_content("河北高考分数线", raw)

    assert "搜索结果" not in cleaned.clean_content
    assert "高级搜索" not in cleaned.clean_content
    assert "展开c" not in cleaned.clean_content
    assert "河北高考分数线公布" in cleaned.clean_content
    assert "物理科目组合443分" in cleaned.clean_content


def test_clean_topic_content_drops_unrelated_hot_list_sidebar_lines():
    raw = """
    从一艘小船到一个大党
    相关新闻正文第一段。
    百度热搜
    1 两名日本人违反中国法律被依法拘留
    2 江苏2026高考分数线公布
    3 消费品以旧换新带动销售额5万亿元
    4 高考查分
    """

    cleaned = clean_topic_content("从一艘小船到一个大党", raw)

    assert "相关新闻正文第一段" in cleaned.clean_content
    assert "江苏2026高考分数线公布" not in cleaned.clean_content
    assert "高考查分" not in cleaned.clean_content


def test_clean_topic_content_preserves_raw_preview_and_limits_clean_content():
    raw = "标题\n" + "\n".join(f"正文第{index}行，包含有效信息。" for index in range(80))

    cleaned = clean_topic_content("标题", raw, max_clean_chars=120, max_raw_preview_chars=30)

    assert cleaned.raw_content_preview.startswith("标题")
    assert len(cleaned.raw_content_preview) <= 30
    assert len(cleaned.clean_content) <= 120
    assert cleaned.content_quality in {"clean", "partial"}


def test_clean_topic_content_falls_back_to_title_when_raw_text_is_empty():
    cleaned = clean_topic_content("河北高考分数线", "")

    assert cleaned.clean_content == "河北高考分数线"
    assert cleaned.content_quality == "fallback"
```

- [ ] **Step 2: Run cleaner tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_topic_content_cleaner.py -q
```

Expected: FAIL because `src.core_pipeline.topic_content_cleaner` does not exist.

- [ ] **Step 3: Implement cleaner module**

Create `src/core_pipeline/topic_content_cleaner.py`:

```python
import re
from dataclasses import dataclass


PAGE_CHROME_LINES = {
    "NEW",
    "搜索结果",
    "综合",
    "智搜",
    "实时",
    "用户",
    "视频",
    "图片",
    "话题",
    "高级搜索",
    "热门",
    "登录",
    "关注",
    "广告",
    "展开c",
    "下一页",
    "百度热搜",
    "刷新",
    "我的",
}

SIDEBAR_PATTERNS = [
    re.compile(r"^\d+\s+.+"),
    re.compile(r"^热搜指数[:：]?\d*"),
    re.compile(r"^查看更多"),
    re.compile(r"^Copyright\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class CleanedContent:
    raw_content_preview: str
    clean_content: str
    removed_line_count: int
    content_quality: str


def clean_topic_content(
    title: str,
    raw_text: str,
    max_clean_chars: int = 800,
    max_raw_preview_chars: int = 500,
) -> CleanedContent:
    raw = str(raw_text or "")
    raw_preview = _truncate(_collapse_spaces(raw), max_raw_preview_chars)
    if not raw.strip():
        fallback = str(title).strip()
        return CleanedContent(
            raw_content_preview="",
            clean_content=fallback,
            removed_line_count=0,
            content_quality="fallback",
        )
    title_terms = _title_terms(title)
    lines = [_clean_line(line) for line in raw.splitlines()]
    kept: list[str] = []
    removed = 0
    sidebar_mode = False
    for line in lines:
        if not line:
            continue
        if _is_page_chrome(line):
            removed += 1
            if line == "百度热搜":
                sidebar_mode = True
            continue
        if sidebar_mode and not _line_matches_title(line, title_terms):
            removed += 1
            continue
        if _is_sidebar_line(line) and not _line_matches_title(line, title_terms):
            removed += 1
            continue
        kept.append(line)
    clean = _truncate(_collapse_spaces("\n".join(_dedupe_adjacent(kept))), max_clean_chars)
    if not clean:
        clean = str(title).strip()
        quality = "fallback"
    elif removed:
        quality = "partial"
    else:
        quality = "clean"
    return CleanedContent(
        raw_content_preview=raw_preview,
        clean_content=clean,
        removed_line_count=removed,
        content_quality=quality,
    )


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _dedupe_adjacent(lines: list[str]) -> list[str]:
    result: list[str] = []
    previous = None
    for line in lines:
        if line == previous:
            continue
        result.append(line)
        previous = line
    return result


def _is_page_chrome(line: str) -> bool:
    return line in PAGE_CHROME_LINES or line.lower() in {"c", "new"}


def _is_sidebar_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in SIDEBAR_PATTERNS)


def _title_terms(title: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", str(title))
    return [term.lower() for term in terms]


def _line_matches_title(line: str, title_terms: list[str]) -> bool:
    normalized = line.lower()
    return any(term and term in normalized for term in title_terms)
```

- [ ] **Step 4: Run cleaner tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_topic_content_cleaner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/topic_content_cleaner.py tests/core_pipeline/test_topic_content_cleaner.py
git commit -m "feat: clean creator topic content"
```

---

### Task 2: Structured Rule And Override Summaries

**Files:**
- Create: `src/core_pipeline/topic_summary.py`
- Create: `tests/core_pipeline/test_topic_summary.py`

- [ ] **Step 1: Write failing summary tests**

Create `tests/core_pipeline/test_topic_summary.py`:

```python
from pathlib import Path
import json
import tempfile

from src.core_pipeline.topic_summary import (
    generate_rule_summary,
    load_manual_summaries,
    select_display_summary,
)


def test_generate_rule_summary_for_education_topic():
    topic = {
        "title": "河北高考分数线",
        "domain_path": ["教育升学", "高考", "分数线"],
        "content_modes": ["数据整理", "实时跟进"],
        "audience_tags": ["学生", "家长"],
        "traceability": "high",
        "risk_level": "low",
    }

    summary = generate_rule_summary(
        topic,
        "河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。",
    )

    assert summary["mode"] == "rule"
    assert "河北高考分数线" in summary["what_happened"]
    assert "学生" in summary["why_it_matters"]
    assert "数据整理" in summary["creator_angle"]
    assert "后续" in summary["tracking_hint"]


def test_select_display_summary_prefers_manual_then_model_then_rule():
    rule = {"mode": "rule", "what_happened": "rule", "why_it_matters": "", "creator_angle": "", "tracking_hint": ""}
    model = {"mode": "model", "what_happened": "model", "why_it_matters": "", "creator_angle": "", "tracking_hint": ""}
    manual = {"mode": "manual", "what_happened": "manual", "why_it_matters": "", "creator_angle": "", "tracking_hint": ""}

    assert select_display_summary({"summary": rule})["what_happened"] == "rule"
    assert select_display_summary({"summary": rule, "model_summary": model})["what_happened"] == "model"
    assert select_display_summary({"summary": rule, "model_summary": model, "manual_summary": manual})["what_happened"] == "manual"


def test_load_manual_summaries_normalizes_shape_by_title():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "topic_summaries.json"
        path.write_text(
            json.dumps(
                {
                    "河北高考分数线": {
                        "what_happened": "人工整理发生了什么",
                        "why_it_matters": "人工整理重要性",
                        "creator_angle": "人工整理创作角度",
                        "tracking_hint": "人工整理追踪点",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        summaries = load_manual_summaries(path)

    assert summaries["河北高考分数线"]["mode"] == "manual"
    assert summaries["河北高考分数线"]["what_happened"] == "人工整理发生了什么"


def test_load_manual_summaries_returns_empty_for_missing_or_invalid_file():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.json"
        invalid = Path(tmp) / "invalid.json"
        invalid.write_text("not json", encoding="utf-8")

        assert load_manual_summaries(missing) == {}
        assert load_manual_summaries(invalid) == {}
```

- [ ] **Step 2: Run summary tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_topic_summary.py -q
```

Expected: FAIL because `src.core_pipeline.topic_summary` does not exist.

- [ ] **Step 3: Implement summary module**

Create `src/core_pipeline/topic_summary.py`:

```python
import json
from pathlib import Path
from typing import Any


SUMMARY_KEYS = ("mode", "what_happened", "why_it_matters", "creator_angle", "tracking_hint")


def generate_rule_summary(topic: dict[str, Any], clean_content: str) -> dict[str, str]:
    title = str(topic.get("title", "")).strip() or "该话题"
    domain_path = [str(item) for item in topic.get("domain_path", [])]
    content_modes = [str(item) for item in topic.get("content_modes", [])]
    audience_tags = [str(item) for item in topic.get("audience_tags", [])]
    domain = " > ".join(domain_path) if domain_path else "未分类"
    audience = "、".join(audience_tags) if audience_tags else "泛大众"
    modes = "、".join(content_modes) if content_modes else "话题跟进"
    first_sentence = _first_sentence(clean_content) or title
    return {
        "mode": "rule",
        "what_happened": first_sentence if title in first_sentence else f"{title}：{first_sentence}",
        "why_it_matters": f"该话题归入{domain}，主要影响或吸引{audience}。",
        "creator_angle": f"适合创作者做{modes}。",
        "tracking_hint": _tracking_hint(topic),
    }


def select_display_summary(card: dict[str, Any]) -> dict[str, str]:
    for key in ("manual_summary", "model_summary", "summary"):
        value = card.get(key)
        if isinstance(value, dict) and value.get("what_happened"):
            return _normalize_summary(value, str(value.get("mode") or key))
    clean_content = str(card.get("clean_content", "")).strip()
    return {
        "mode": "fallback",
        "what_happened": _first_sentence(clean_content) or "暂无摘要。",
        "why_it_matters": "",
        "creator_angle": "",
        "tracking_hint": "",
    }


def load_manual_summaries(path: str | Path) -> dict[str, dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    summaries: dict[str, dict[str, str]] = {}
    for title, summary in data.items():
        if isinstance(summary, dict):
            summaries[str(title)] = _normalize_summary(summary, "manual")
    return summaries


def _normalize_summary(summary: dict[str, Any], mode: str) -> dict[str, str]:
    return {
        "mode": str(summary.get("mode") or mode),
        "what_happened": str(summary.get("what_happened", "")).strip(),
        "why_it_matters": str(summary.get("why_it_matters", "")).strip(),
        "creator_angle": str(summary.get("creator_angle", "")).strip(),
        "tracking_hint": str(summary.get("tracking_hint", "")).strip(),
    }


def _first_sentence(text: str) -> str:
    compact = " ".join(str(text or "").split())
    if not compact:
        return ""
    for marker in ("。", "！", "？", ".", "!", "?"):
        if marker in compact:
            return compact.split(marker, 1)[0].strip() + marker
    return compact[:120].strip()


def _tracking_hint(topic: dict[str, Any]) -> str:
    traceability = str(topic.get("traceability", ""))
    domain_path = [str(item) for item in topic.get("domain_path", [])]
    if "高考" in domain_path:
        return "后续可追踪志愿填报时间、录取批次变化和考生反馈。"
    if traceability == "high":
        return "后续可追踪官方更新、平台讨论变化和相关事件进展。"
    if traceability == "medium":
        return "后续可观察是否出现官方补充信息或跨平台扩散。"
    return "可低频观察，若没有新信息不建议持续追。"
```

- [ ] **Step 4: Run summary tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_topic_summary.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core_pipeline/topic_summary.py tests/core_pipeline/test_topic_summary.py
git commit -m "feat: summarize creator topic cards"
```

---

### Task 3: Integrate Cleaner And Summaries Into Index Cards

**Files:**
- Modify: `src/core_pipeline/creator_topic_classifier.py`
- Modify: `tests/core_pipeline/test_creator_topic_classifier.py`

- [ ] **Step 1: Write failing card-shape tests**

Append to `tests/core_pipeline/test_creator_topic_classifier.py`:

```python
def test_classify_topic_card_contains_clean_content_and_structured_summary():
    topic = {
        "topic_id": "topic_001",
        "topic_key": "河北高考分数线",
        "canonical_title": "河北高考分数线",
        "hot_record_ids": ["hot_weibo_001"],
        "platforms": ["weibo"],
        "best_rank": 1,
    }
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
            "content": "搜索结果\n综合\n河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。\n展开c",
            "url": "https://example.com/weibo",
        }
    ]

    result = classify_topic(topic, records, details)
    card = result["card"]

    assert "搜索结果" not in card["clean_content"]
    assert "河北高考分数线公布" in card["clean_content"]
    assert card["raw_content_preview"].startswith("搜索结果")
    assert card["summary"]["mode"] == "rule"
    assert card["summary"]["what_happened"]
    assert card["manual_summary"] is None
    assert card["model_summary"] is None
    assert card["risk_note"]


def test_build_creator_topic_index_applies_manual_summary_override():
    topics = [
        {
            "topic_key": "河北高考分数线",
            "canonical_title": "河北高考分数线",
            "hot_record_ids": [],
            "platforms": ["weibo"],
            "best_rank": 1,
        }
    ]
    manual_summaries = {
        "河北高考分数线": {
            "mode": "manual",
            "what_happened": "人工摘要：河北分数线公布。",
            "why_it_matters": "人工摘要：影响志愿填报。",
            "creator_angle": "人工摘要：适合做本地教育解读。",
            "tracking_hint": "人工摘要：追踪志愿填报节点。",
        }
    }

    index = build_creator_topic_index(
        topics=topics,
        hot_records=[],
        detail_rows=[],
        generated_at="2026-06-24T16:00:00+08:00",
        source_files=[],
        manual_summaries=manual_summaries,
    )

    assert index["topics"][0]["card"]["manual_summary"]["what_happened"] == "人工摘要：河北分数线公布。"
```

- [ ] **Step 2: Run classifier tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_creator_topic_classifier.py -q
```

Expected: FAIL because the card lacks `clean_content`, structured summaries, and `manual_summaries` parameters.

- [ ] **Step 3: Integrate cleaner and summary modules**

Modify imports in `src/core_pipeline/creator_topic_classifier.py`:

```python
from src.core_pipeline.topic_content_cleaner import clean_topic_content
from src.core_pipeline.topic_summary import generate_rule_summary
```

Change `classify_topic` signature:

```python
def classify_topic(
    topic: dict[str, Any],
    hot_records: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    manual_summaries: dict[str, dict[str, str]] | None = None,
    model_summaries: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
```

Replace the existing `detail = _detail_text(related_details)` and card construction with:

```python
    raw_detail = _detail_text(related_details)
    cleaned = clean_topic_content(title, raw_detail)
    summary_topic = {
        "title": title,
        "domain_path": domain_path,
        "content_modes": content_modes,
        "audience_tags": audience_tags,
        "traceability": traceability,
        "risk_level": risk_level,
    }
    rule_summary = generate_rule_summary(summary_topic, cleaned.clean_content)
    manual_summary = (manual_summaries or {}).get(title) or (manual_summaries or {}).get(topic_key)
    model_summary = (model_summaries or {}).get(title) or (model_summaries or {}).get(topic_key)
```

Then update the returned `card` value:

```python
        "card": {
            "source_platforms": platforms,
            "hotness_label": _hotness_label(hotness),
            "raw_content_preview": cleaned.raw_content_preview,
            "clean_content": cleaned.clean_content,
            "summary": rule_summary,
            "manual_summary": manual_summary,
            "model_summary": model_summary,
            "risk_note": _risk_note(risk_level, domain_path),
            "content_quality": cleaned.content_quality,
            "removed_line_count": cleaned.removed_line_count,
            "evidence_urls": _evidence_urls(related_details),
        },
```

Add helpers:

```python
def _hotness_label(hotness: TopicHotness) -> str:
    rank = f"排名 {hotness.best_rank}" if hotness.best_rank is not None else "排名未知"
    values = [
        f"{row['platform']}热度 {row['value']}"
        for row in hotness.hot_values
        if row.get("platform") or row.get("value")
    ]
    return "；".join([rank] + values)


def _risk_note(risk_level: str, domain_path: list[str]) -> str:
    if risk_level == "high":
        return "高风险话题，发布前需核对权威来源并谨慎表达。"
    if risk_level == "medium":
        return "存在争议或专业风险，建议补充可靠来源和上下文。"
    if "教育升学" in domain_path:
        return "教育信息需核对官方来源。"
    return "常规风险，注意核对来源。"
```

Change `build_creator_topic_index` signature:

```python
def build_creator_topic_index(
    topics: list[dict[str, Any]],
    hot_records: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    generated_at: str,
    source_files: list[str],
    manual_summaries: dict[str, dict[str, str]] | None = None,
    model_summaries: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
```

Change the call inside `build_creator_topic_index`:

```python
topic_records.append(
    classify_topic(
        enriched_topic,
        hot_records,
        detail_rows,
        manual_summaries=manual_summaries,
        model_summaries=model_summaries,
    )
)
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
git commit -m "feat: add cleaned content to creator index"
```

---

### Task 4: Creator-Facing Markdown Renderer

**Files:**
- Modify: `src/core_pipeline/report_renderer.py`
- Modify: `tests/core_pipeline/test_report_renderer.py`

- [ ] **Step 1: Replace old creator-card renderer test**

In `tests/core_pipeline/test_report_renderer.py`, replace `test_render_creator_topic_cards_groups_by_domain_and_shows_card_fields` with:

```python
def test_render_creator_topic_cards_uses_structured_summary_layout():
    index = {
        "generated_at": "2026-06-24T16:00:00+08:00",
        "topics": [
            {
                "title": "河北高考分数线",
                "domain_path": ["教育升学", "高考", "分数线"],
                "content_modes": ["数据整理", "经验攻略"],
                "audience_tags": ["学生", "家长"],
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
                    "hotness_label": "排名 1；weibo热度 1784276",
                    "clean_content": "河北公布 2026 年高考分数线。",
                    "summary": {
                        "mode": "rule",
                        "what_happened": "河北公布 2026 年高考分数线。",
                        "why_it_matters": "影响学生和家长志愿填报。",
                        "creator_angle": "适合做分数线汇总。",
                        "tracking_hint": "后续可追踪志愿填报时间。",
                    },
                    "manual_summary": None,
                    "model_summary": None,
                    "risk_note": "教育信息需核对官方来源。",
                    "evidence_urls": ["https://example.com/weibo"],
                },
            }
        ],
    }

    markdown = render_creator_topic_cards(index)

    assert "# 创作者热点卡片" in markdown
    assert "## 教育升学" in markdown
    assert "### 河北高考分数线" in markdown
    assert "热度与平台：排名 1；weibo热度 1784276；来源 weibo" in markdown
    assert "分类与受众：教育升学 > 高考 > 分数线；学生、家长" in markdown
    assert "一句话：河北公布 2026 年高考分数线。" in markdown
    assert "具体内容：" in markdown
    assert "创作者角度：" in markdown
    assert "可追踪点：" in markdown
    assert "风险提示：" in markdown
```

- [ ] **Step 2: Run renderer test to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_report_renderer.py::test_render_creator_topic_cards_uses_structured_summary_layout -q
```

Expected: FAIL because the renderer still uses the old internal-field layout.

- [ ] **Step 3: Implement structured card renderer**

Modify imports in `src/core_pipeline/report_renderer.py`:

```python
from src.core_pipeline.topic_summary import select_display_summary
```

Replace `render_creator_topic_cards` with:

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
            card = topic.get("card", {}) if isinstance(topic.get("card"), dict) else {}
            summary = select_display_summary(card)
            source_platforms = card.get("source_platforms", [])
            lines.extend(
                [
                    f"### {topic.get('title', '未命名话题')}",
                    "",
                    f"热度与平台：{card.get('hotness_label', '')}；来源 {', '.join(str(item) for item in source_platforms)}",
                    f"分类与受众：{' > '.join(str(item) for item in topic.get('domain_path', []))}；{'、'.join(str(item) for item in topic.get('audience_tags', []))}",
                    f"适合创作：{'、'.join(str(item) for item in topic.get('content_modes', []))}",
                    "",
                    f"一句话：{summary.get('what_happened', '')}",
                    "",
                    "具体内容：",
                    "",
                    str(card.get("clean_content", "")),
                    "",
                    "创作者角度：",
                    "",
                    summary.get("creator_angle", ""),
                    "",
                    "可追踪点：",
                    "",
                    summary.get("tracking_hint", ""),
                    "",
                    "风险提示：",
                    "",
                    str(card.get("risk_note", "")),
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
```

Leave `_format_hot_values` in place for now if older tests still import or use it indirectly. It can be removed later if unused.

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
git commit -m "feat: render structured creator cards"
```

---

### Task 5: Command Options For Manual And Model Summary Modes

**Files:**
- Modify: `src/core_pipeline/run.py`
- Modify: `tests/core_pipeline/test_run.py`

- [ ] **Step 1: Write failing command tests**

Add tests to `tests/core_pipeline/test_run.py`:

```python
    def test_build_creator_topic_index_command_uses_manual_summary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/raw").mkdir(parents=True)
            (root / "data/evidence").mkdir(parents=True)
            (root / "data/processed").mkdir(parents=True)
            manual_path = root / "manual.json"
            (root / "data/raw/dailyhot_records.json").write_text("[]", encoding="utf-8")
            (root / "data/evidence/detail_evidence_raw.jsonl").write_text("", encoding="utf-8")
            (root / "data/processed/topic_clusters.json").write_text(
                json.dumps(
                    [
                        {
                            "topic_key": "河北高考分数线",
                            "canonical_title": "河北高考分数线",
                            "hot_record_ids": [],
                            "platforms": ["weibo"],
                            "best_rank": 1,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manual_path.write_text(
                json.dumps(
                    {
                        "河北高考分数线": {
                            "what_happened": "人工摘要：河北分数线公布。",
                            "why_it_matters": "人工摘要：影响志愿填报。",
                            "creator_angle": "人工摘要：适合本地教育号。",
                            "tracking_hint": "人工摘要：追踪志愿节点。",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build_creator_topic_index_command(
                root=root,
                generated_at="2026-06-24T16:00:00+08:00",
                render_report=True,
                manual_summaries_path=manual_path,
            )

            index = json.loads((root / "data/processed/creator_topic_index.json").read_text(encoding="utf-8"))
            card = index["topics"][0]["card"]
            self.assertEqual(card["manual_summary"]["what_happened"], "人工摘要：河北分数线公布。")
            self.assertIn("人工摘要：河北分数线公布。", (root / "reports/creator_topic_cards.md").read_text(encoding="utf-8"))

    def test_main_accepts_manual_summaries_and_summary_mode_flags(self):
        calls = []

        def fake_command(**kwargs):
            calls.append(kwargs)
            return {"topics_count": 0}

        with patch(
            "sys.argv",
            [
                "run.py",
                "build-creator-topic-index",
                "--render-report",
                "--manual-summaries",
                "data/manual/topic_summaries.json",
                "--summary-mode",
                "model",
            ],
        ):
            with patch("src.core_pipeline.run.build_creator_topic_index_command", fake_command):
                main()

        self.assertEqual(calls[0]["manual_summaries_path"], Path("data/manual/topic_summaries.json"))
        self.assertEqual(calls[0]["summary_mode"], "model")
```

- [ ] **Step 2: Run run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_run.py::RunTests::test_build_creator_topic_index_command_uses_manual_summary_file tests/core_pipeline/test_run.py::RunTests::test_main_accepts_manual_summaries_and_summary_mode_flags -q
```

Expected: FAIL because the command does not accept manual/model summary options.

- [ ] **Step 3: Wire manual summaries and summary mode**

Modify imports in `src/core_pipeline/run.py`:

```python
from src.core_pipeline.topic_summary import load_manual_summaries
```

Change `build_creator_topic_index_command` signature:

```python
def build_creator_topic_index_command(
    root: Path = Path("."),
    generated_at: str | None = None,
    render_report: bool = False,
    manual_summaries_path: Path | None = None,
    summary_mode: str = "rule",
) -> dict[str, int]:
```

Add before `index = build_creator_topic_index(...)`:

```python
    manual_summaries = load_manual_summaries(manual_summaries_path) if manual_summaries_path is not None else {}
    if summary_mode == "model":
        print("[提示] model summary mode is reserved; using rule/manual summaries in this build.", file=sys.stderr)
```

Pass summaries into `build_creator_topic_index`:

```python
        manual_summaries=manual_summaries,
        model_summaries={},
```

Add parser args:

```python
parser.add_argument("--manual-summaries", default="")
parser.add_argument("--summary-mode", choices=("rule", "model"), default="rule")
```

Update the command branch:

```python
if args.command == "build-creator-topic-index":
    manual_summaries_path = Path(args.manual_summaries) if args.manual_summaries else None
    build_creator_topic_index_command(
        root=Path("."),
        render_report=args.render_report,
        manual_summaries_path=manual_summaries_path,
        summary_mode=args.summary_mode,
    )
```

- [ ] **Step 4: Run selected run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_run.py::RunTests::test_build_creator_topic_index_command_uses_manual_summary_file tests/core_pipeline/test_run.py::RunTests::test_main_accepts_manual_summaries_and_summary_mode_flags -q
```

Expected: PASS.

- [ ] **Step 5: Run all command tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_run.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/core_pipeline/run.py tests/core_pipeline/test_run.py
git commit -m "feat: support creator card summary inputs"
```

---

### Task 6: End-To-End Regeneration And Verification

**Files:**
- Generated: `data/processed/creator_topic_index.json`
- Generated: `reports/creator_topic_cards.md`

- [ ] **Step 1: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline/test_topic_content_cleaner.py tests/core_pipeline/test_topic_summary.py tests/core_pipeline/test_creator_topic_classifier.py tests/core_pipeline/test_report_renderer.py tests/core_pipeline/test_run.py -q
```

Expected: PASS.

- [ ] **Step 2: Regenerate creator index and report from current data**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run build-creator-topic-index --render-report
```

Expected:

- Command exits with code 0.
- Output says it generated a positive number of topics.
- `data/processed/creator_topic_index.json` exists.
- `reports/creator_topic_cards.md` exists.

- [ ] **Step 3: Inspect generated card shape**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
@'
import json
from pathlib import Path
index = json.loads(Path("data/processed/creator_topic_index.json").read_text(encoding="utf-8"))
topic = index["topics"][0]
card = topic["card"]
print(index["schema_version"])
print(len(index["topics"]))
print(sorted(card.keys()))
print(card["summary"]["mode"])
print(card["clean_content"][:80])
'@ | python -
```

Expected:

- First line: `1.0`
- Second line: positive integer
- Card keys include `clean_content`, `raw_content_preview`, `summary`, `manual_summary`, `model_summary`, and `risk_note`
- Summary mode is `rule` unless manual summaries were supplied

- [ ] **Step 4: Inspect Markdown layout**

Run:

```powershell
Get-Content -Encoding utf8 reports\creator_topic_cards.md -TotalCount 80
```

Expected output contains:

- `热度与平台：`
- `分类与受众：`
- `一句话：`
- `创作者角度：`
- `可追踪点：`
- `风险提示：`

- [ ] **Step 5: Run broader core tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/core_pipeline -q
```

Expected: PASS.

- [ ] **Step 6: Commit source, tests, and optionally generated artifacts**

If generated data and reports are meant to stay untracked, commit only source/tests:

```powershell
git add src/core_pipeline tests/core_pipeline
git commit -m "feat: improve creator card cleaning and summaries"
```

If the generated artifacts should be versioned in this branch, include them:

```powershell
git add src/core_pipeline tests/core_pipeline data/processed/creator_topic_index.json reports/creator_topic_cards.md
git commit -m "feat: improve creator card cleaning and summaries"
```

---

## Self-Review

Spec coverage:

- Three-layer content pipeline: Tasks 1 and 3.
- Richer `card` JSON shape: Task 3.
- Summary priority: Task 2 and Task 4.
- Creator-facing Markdown layout: Task 4.
- Deterministic cleaning: Task 1.
- Rule summaries: Task 2.
- Manual summaries: Task 2 and Task 5.
- Model summaries optional/non-blocking: Task 5.
- Error handling for missing/invalid manual files and empty content: Tasks 1, 2, and 5.
- Regeneration and verification: Task 6.

Placeholder scan:

- No task contains placeholder or fill-in steps.
- Each code-changing step includes concrete code.
- Each test step includes exact commands and expected outcomes.

Type consistency:

- `CleanedContent` exposes `raw_content_preview`, `clean_content`, `removed_line_count`, and `content_quality`.
- Summary dictionaries always contain `mode`, `what_happened`, `why_it_matters`, `creator_angle`, and `tracking_hint`.
- `manual_summaries` and `model_summaries` are dictionaries keyed by title or topic key.
- `render_creator_topic_cards` consumes the new `card` shape and uses `select_display_summary`.
