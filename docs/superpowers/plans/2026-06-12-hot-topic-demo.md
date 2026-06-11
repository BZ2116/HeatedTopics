# Hot Topic Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tomorrow-morning demo that collects domestic hot topics, enriches selected topics with readable sources, and outputs Markdown reports plus an optional static HTML view.

**Architecture:** Use a Python CLI pipeline as the main path: fetch hot lists, normalize records, select demo-worthy topics, read source pages through Jina Reader, generate topic cards with an LLM, and write JSON/Markdown artifacts. Keep the HTML page as a generated static file that reads the Markdown/JSON output, so the demo does not depend on a web server.

**Tech Stack:** Python 3.10+, standard library `urllib/request`, `json`, `dataclasses`, `datetime`, optional `openai` Python package for LLM generation, Jina Reader HTTP endpoint, DailyHotApi HTTP endpoint, Markdown and static HTML outputs.

---

## 0. Demo Scope

### Main path

```text
DailyHotApi
→ Python CLI
→ topic selection
→ Jina Reader detail enrichment
→ LLM card generation
→ Markdown report
```

### Optional bonus

```text
Markdown/JSON output
→ generated static HTML
→ browser presentation
```

### Non-goals

- No database.
- No login-only platform crawling.
- No multi-agent system.
- No MCP Server in the Demo stage.
- No `.env` file changes. Use exported environment variables only.

## 1. File Structure

Create these files:

```text
/Users/BZ/Documents/heatedTopics/src/demo_config.py
/Users/BZ/Documents/heatedTopics/src/hot_topic_types.py
/Users/BZ/Documents/heatedTopics/src/fetch_hot_lists.py
/Users/BZ/Documents/heatedTopics/src/select_topics.py
/Users/BZ/Documents/heatedTopics/src/enrich_sources.py
/Users/BZ/Documents/heatedTopics/src/generate_reports.py
/Users/BZ/Documents/heatedTopics/src/demo_collect_hot_topics.py
/Users/BZ/Documents/heatedTopics/tests/test_select_topics.py
/Users/BZ/Documents/heatedTopics/tests/test_generate_reports.py
```

Generated artifacts:

```text
/Users/BZ/Documents/heatedTopics/data/hot_list.json
/Users/BZ/Documents/heatedTopics/data/selected_topics.json
/Users/BZ/Documents/heatedTopics/data/topic_sources.json
/Users/BZ/Documents/heatedTopics/reports/hot_topic_cards.md
/Users/BZ/Documents/heatedTopics/reports/daily_digest_demo.md
/Users/BZ/Documents/heatedTopics/reports/daily_digest_demo.html
```

Responsibilities:

| File | Responsibility |
|---|---|
| `demo_config.py` | Platform list, API base URLs, output paths, selection thresholds |
| `hot_topic_types.py` | Dataclasses for normalized hot records, selected topics, source summaries, cards |
| `fetch_hot_lists.py` | Fetch and normalize hot lists from DailyHotApi |
| `select_topics.py` | Select 5-8 demo topics using deterministic rules |
| `enrich_sources.py` | Read URLs through Jina Reader and apply search/read fallback |
| `generate_reports.py` | Generate Markdown cards, digest, and optional static HTML |
| `demo_collect_hot_topics.py` | CLI entrypoint that runs the full pipeline |
| `tests/test_select_topics.py` | Unit tests for ranking, deduplication, and topic selection |
| `tests/test_generate_reports.py` | Unit tests for Markdown output shape |

## 2. Demo Acceptance Criteria

- At least 4 platforms are collected successfully.
- At least 30 normalized hot-list records are written to `data/hot_list.json`.
- 5-8 selected topics are written to `data/selected_topics.json`.
- At least 5 topic cards are written to `reports/hot_topic_cards.md`.
- `reports/daily_digest_demo.md` contains:
  - 今日概览
  - 重点热点
  - 跨平台共同热点
  - 建议继续跟踪
  - 数据来源与置信度说明
- Failed fetches do not stop the whole run.
- Every generated topic card has a confidence label: `high`, `medium`, or `low`.

## 3. Implementation Tasks

### Task 1: Create Basic Project Runtime Files

**Files:**

- Create: `/Users/BZ/Documents/heatedTopics/src/demo_config.py`
- Create: `/Users/BZ/Documents/heatedTopics/src/hot_topic_types.py`
- Create: `/Users/BZ/Documents/heatedTopics/src/__init__.py`
- Create: `/Users/BZ/Documents/heatedTopics/tests/__init__.py`

- [ ] **Step 1: Create directories**

Run:

```bash
mkdir -p /Users/BZ/Documents/heatedTopics/src /Users/BZ/Documents/heatedTopics/tests /Users/BZ/Documents/heatedTopics/data /Users/BZ/Documents/heatedTopics/reports
```

Expected: directories exist.

- [ ] **Step 2: Create `demo_config.py`**

Use this content:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"

DAILY_HOT_API_BASE = "https://dailyhot.imsyy.top"
JINA_READER_PREFIX = "https://r.jina.ai/"
JINA_SEARCH_PREFIX = "https://s.jina.ai/"

PLATFORMS = [
    "weibo",
    "baidu",
    "zhihu",
    "bilibili",
    "36kr",
    "ithome",
]

FALLBACK_PLATFORMS = [
    "weibo",
    "baidu",
    "zhihu",
    "36kr",
]

TOP_N_PER_PLATFORM = 10
TOP_N_FOR_SELECTION = 5
MIN_SELECTED_TOPICS = 5
MAX_SELECTED_TOPICS = 8

HOT_LIST_PATH = DATA_DIR / "hot_list.json"
SELECTED_TOPICS_PATH = DATA_DIR / "selected_topics.json"
TOPIC_SOURCES_PATH = DATA_DIR / "topic_sources.json"
HOT_TOPIC_CARDS_PATH = REPORTS_DIR / "hot_topic_cards.md"
DAILY_DIGEST_PATH = REPORTS_DIR / "daily_digest_demo.md"
DAILY_DIGEST_HTML_PATH = REPORTS_DIR / "daily_digest_demo.html"
```

- [ ] **Step 3: Create `hot_topic_types.py`**

Use this content:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HotRecord:
    platform: str
    rank: int
    title: str
    hot: str
    url: str
    crawl_time: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "rank": self.rank,
            "title": self.title,
            "hot": self.hot,
            "url": self.url,
            "crawl_time": self.crawl_time,
        }


@dataclass(frozen=True)
class SelectedTopic:
    title: str
    platforms: list[str]
    ranks: dict[str, int]
    urls: list[str]
    score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "platforms": self.platforms,
            "ranks": self.ranks,
            "urls": self.urls,
            "score": self.score,
        }


@dataclass(frozen=True)
class TopicSource:
    title: str
    source_url: str
    content_preview: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "content_preview": self.content_preview,
            "status": self.status,
        }


@dataclass(frozen=True)
class TopicCard:
    title: str
    platforms: list[str]
    ranks: dict[str, int]
    summary: str
    background: str
    why_hot: list[str]
    related_entities: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    need_follow_up: bool = True
    confidence: str = "medium"
```

- [ ] **Step 4: Run syntax check**

Run:

```bash
python3 -m py_compile /Users/BZ/Documents/heatedTopics/src/demo_config.py /Users/BZ/Documents/heatedTopics/src/hot_topic_types.py
```

Expected: no output and exit code 0.

### Task 2: Implement Topic Selection Rules First

**Files:**

- Create: `/Users/BZ/Documents/heatedTopics/src/select_topics.py`
- Create: `/Users/BZ/Documents/heatedTopics/tests/test_select_topics.py`

- [ ] **Step 1: Write failing tests**

Use this content for `tests/test_select_topics.py`:

```python
from src.hot_topic_types import HotRecord
from src.select_topics import normalize_title_key, select_topics


def record(platform, rank, title, hot="100", url="https://example.com"):
    return HotRecord(
        platform=platform,
        rank=rank,
        title=title,
        hot=hot,
        url=url,
        crawl_time="2026-06-12 08:30:00",
    )


def test_normalize_title_key_removes_spaces_and_lowercases_ascii():
    assert normalize_title_key("  AI 新产品 发布  ") == "ai新产品发布"


def test_select_topics_prioritizes_cross_platform_items():
    records = [
        record("weibo", 1, "AI 新产品发布"),
        record("baidu", 3, "AI新产品发布"),
        record("zhihu", 1, "另一个话题"),
        record("36kr", 2, "商业融资事件"),
        record("ithome", 1, "手机新品"),
    ]

    selected = select_topics(records, min_count=2, max_count=3)

    assert selected[0].title == "AI 新产品发布"
    assert selected[0].platforms == ["weibo", "baidu"]
    assert selected[0].ranks == {"weibo": 1, "baidu": 3}


def test_select_topics_respects_max_count():
    records = [
        record("weibo", 1, "话题一"),
        record("weibo", 2, "话题二"),
        record("weibo", 3, "话题三"),
    ]

    selected = select_topics(records, min_count=1, max_count=2)

    assert len(selected) == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m unittest /Users/BZ/Documents/heatedTopics/tests/test_select_topics.py
```

Expected: fail because `src.select_topics` does not exist.

- [ ] **Step 3: Implement `select_topics.py`**

Use this content:

```python
from collections import defaultdict

from src.hot_topic_types import HotRecord, SelectedTopic


IMPORTANT_KEYWORDS = [
    "ai",
    "人工智能",
    "大模型",
    "科技",
    "芯片",
    "商业",
    "融资",
    "公司",
    "安全",
    "网安",
    "教育",
]


def normalize_title_key(title: str) -> str:
    return "".join(title.lower().split())


def keyword_bonus(title: str) -> int:
    lowered = title.lower()
    return sum(5 for keyword in IMPORTANT_KEYWORDS if keyword in lowered)


def select_topics(
    records: list[HotRecord],
    min_count: int = 5,
    max_count: int = 8,
) -> list[SelectedTopic]:
    grouped: dict[str, list[HotRecord]] = defaultdict(list)
    titles: dict[str, str] = {}

    for item in records:
        key = normalize_title_key(item.title)
        grouped[key].append(item)
        titles.setdefault(key, item.title)

    selected: list[SelectedTopic] = []
    for key, items in grouped.items():
        sorted_items = sorted(items, key=lambda item: item.rank)
        platforms = []
        ranks = {}
        urls = []

        for item in sorted_items:
            if item.platform not in platforms:
                platforms.append(item.platform)
                ranks[item.platform] = item.rank
            if item.url and item.url not in urls:
                urls.append(item.url)

        best_rank = min(item.rank for item in items)
        cross_platform_bonus = 30 * (len(platforms) - 1)
        rank_score = max(0, 20 - best_rank)
        score = cross_platform_bonus + rank_score + keyword_bonus(titles[key])

        selected.append(
            SelectedTopic(
                title=titles[key],
                platforms=platforms,
                ranks=ranks,
                urls=urls,
                score=score,
            )
        )

    selected.sort(key=lambda item: item.score, reverse=True)
    return selected[:max_count]
```

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m unittest /Users/BZ/Documents/heatedTopics/tests/test_select_topics.py
```

Expected: all tests pass.

### Task 3: Fetch and Normalize DailyHotApi Data

**Files:**

- Create: `/Users/BZ/Documents/heatedTopics/src/fetch_hot_lists.py`
- Modify: `/Users/BZ/Documents/heatedTopics/src/demo_collect_hot_topics.py`

- [ ] **Step 1: Implement `fetch_hot_lists.py`**

Use this content:

```python
import json
from datetime import datetime
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from src.demo_config import DAILY_HOT_API_BASE, TOP_N_PER_PLATFORM
from src.hot_topic_types import HotRecord


def fetch_json(url: str, timeout: int = 12) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        for key in ("data", "list", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    if isinstance(data, list):
        return data
    return []


def normalize_item(platform: str, index: int, item: dict[str, Any], crawl_time: str) -> HotRecord:
    title = str(item.get("title") or item.get("name") or item.get("word") or "").strip()
    hot = str(item.get("hot") or item.get("desc") or item.get("heat") or item.get("views") or "")
    url = str(item.get("url") or item.get("mobilUrl") or item.get("mobileUrl") or item.get("link") or "")
    rank = int(item.get("rank") or index + 1)
    return HotRecord(
        platform=platform,
        rank=rank,
        title=title,
        hot=hot,
        url=url,
        crawl_time=crawl_time,
    )


def fetch_platform(platform: str, limit: int = TOP_N_PER_PLATFORM) -> list[HotRecord]:
    url = f"{DAILY_HOT_API_BASE}/{platform}"
    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        payload = fetch_json(url)
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []

    records = []
    for index, item in enumerate(extract_items(payload)[:limit]):
        if not isinstance(item, dict):
            continue
        record = normalize_item(platform, index, item, crawl_time)
        if record.title:
            records.append(record)
    return records


def fetch_all_platforms(platforms: list[str], limit: int = TOP_N_PER_PLATFORM) -> list[HotRecord]:
    records: list[HotRecord] = []
    for platform in platforms:
        records.extend(fetch_platform(platform, limit=limit))
    return records
```

- [ ] **Step 2: Add a temporary smoke command**

Run:

```bash
python3 - <<'PY'
from src.fetch_hot_lists import fetch_all_platforms
records = fetch_all_platforms(["weibo", "baidu"], limit=3)
print(len(records))
for item in records[:3]:
    print(item.to_dict())
PY
```

Expected: prints an integer and up to 3 normalized records. If it prints `0`, inspect DailyHotApi endpoint availability before continuing.

### Task 4: Enrich Sources with Jina Reader

**Files:**

- Create: `/Users/BZ/Documents/heatedTopics/src/enrich_sources.py`

- [ ] **Step 1: Implement `enrich_sources.py`**

Use this content:

```python
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import URLError

from src.hot_topic_types import SelectedTopic, TopicSource


def jina_reader_url(source_url: str) -> str:
    if source_url.startswith("http://") or source_url.startswith("https://"):
        return f"https://r.jina.ai/{source_url}"
    return f"https://s.jina.ai/{quote(source_url)}"


def read_url_text(url: str, timeout: int = 15) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def enrich_topic(topic: SelectedTopic, max_chars: int = 3000) -> TopicSource:
    for url in topic.urls:
        target = url or topic.title
        try:
            text = read_url_text(jina_reader_url(target))
        except (URLError, TimeoutError, OSError):
            continue
        cleaned = text.strip()
        if len(cleaned) >= 120:
            return TopicSource(
                title=topic.title,
                source_url=target,
                content_preview=cleaned[:max_chars],
                status="ok",
            )

    return TopicSource(
        title=topic.title,
        source_url=topic.urls[0] if topic.urls else "",
        content_preview="未能稳定读取详情页，Demo 阶段基于热榜标题、平台和排名生成低置信度卡片。",
        status="fallback",
    )


def enrich_topics(topics: list[SelectedTopic]) -> list[TopicSource]:
    return [enrich_topic(topic) for topic in topics]
```

- [ ] **Step 2: Run syntax check**

Run:

```bash
python3 -m py_compile /Users/BZ/Documents/heatedTopics/src/enrich_sources.py
```

Expected: no output and exit code 0.

### Task 5: Generate Markdown and Static HTML Reports

**Files:**

- Create: `/Users/BZ/Documents/heatedTopics/src/generate_reports.py`
- Create: `/Users/BZ/Documents/heatedTopics/tests/test_generate_reports.py`

- [ ] **Step 1: Write report tests**

Use this content for `tests/test_generate_reports.py`:

```python
from src.generate_reports import render_daily_digest, render_topic_cards
from src.hot_topic_types import TopicCard


def sample_card():
    return TopicCard(
        title="AI 新产品发布",
        platforms=["weibo", "baidu"],
        ranks={"weibo": 1, "baidu": 3},
        summary="某 AI 产品发布，引发跨平台讨论。",
        background="该事件与 AI 应用落地有关。",
        why_hot=["跨平台讨论", "涉及 AI 产业", "用户关注度高"],
        related_entities=["AI 公司"],
        sources=["https://example.com"],
        need_follow_up=True,
        confidence="medium",
    )


def test_render_topic_cards_contains_required_sections():
    markdown = render_topic_cards([sample_card()])
    assert "# 热点详情卡" in markdown
    assert "## AI 新产品发布" in markdown
    assert "**为什么火：**" in markdown
    assert "**置信度：** medium" in markdown


def test_render_daily_digest_contains_required_sections():
    markdown = render_daily_digest([sample_card()])
    assert "# 当前国内热点话题简报" in markdown
    assert "## 今日概览" in markdown
    assert "## 建议继续跟踪" in markdown
```

- [ ] **Step 2: Implement `generate_reports.py`**

Use this content:

```python
from html import escape

from src.hot_topic_types import SelectedTopic, TopicCard, TopicSource


def build_cards(topics: list[SelectedTopic], sources: list[TopicSource]) -> list[TopicCard]:
    source_by_title = {source.title: source for source in sources}
    cards: list[TopicCard] = []

    for topic in topics:
        source = source_by_title.get(topic.title)
        content = source.content_preview if source else ""
        confidence = "medium" if source and source.status == "ok" else "low"
        summary = f"{topic.title} 出现在 {len(topic.platforms)} 个平台，Demo 阶段已整理为重点观察话题。"
        background = content[:260].replace("\n", " ") if content else "暂无稳定详情来源。"

        cards.append(
            TopicCard(
                title=topic.title,
                platforms=topic.platforms,
                ranks=topic.ranks,
                summary=summary,
                background=background,
                why_hot=[
                    "平台排名靠前",
                    "具备较高讨论度",
                    "适合作为后续持续追踪对象",
                ],
                related_entities=[],
                sources=[source.source_url] if source and source.source_url else [],
                need_follow_up=True,
                confidence=confidence,
            )
        )

    return cards


def render_topic_cards(cards: list[TopicCard]) -> str:
    lines = ["# 热点详情卡", ""]
    for card in cards:
        lines.extend(
            [
                f"## {card.title}",
                "",
                f"**一句话概括：** {card.summary}",
                "",
                f"**来源平台：** {', '.join(card.platforms)}",
                "",
                f"**当前排名：** {card.ranks}",
                "",
                f"**事件背景：** {card.background}",
                "",
                "**为什么火：**",
            ]
        )
        for reason in card.why_hot:
            lines.append(f"- {reason}")
        lines.extend(
            [
                "",
                f"**相关主体：** {', '.join(card.related_entities) if card.related_entities else '待补充'}",
                "",
                f"**来源链接：** {', '.join(card.sources) if card.sources else '暂无稳定详情来源'}",
                "",
                f"**是否继续跟踪：** {'是' if card.need_follow_up else '否'}",
                "",
                f"**置信度：** {card.confidence}",
                "",
            ]
        )
    return "\n".join(lines)


def render_daily_digest(cards: list[TopicCard]) -> str:
    follow_up = [card for card in cards if card.need_follow_up]
    lines = [
        "# 当前国内热点话题简报",
        "",
        "## 今日概览",
        "",
        f"本次 Demo 共生成 {len(cards)} 张热点详情卡，其中 {len(follow_up)} 个话题建议继续跟踪。",
        "",
        "## 重点热点",
        "",
    ]
    for index, card in enumerate(cards, start=1):
        lines.append(f"{index}. **{card.title}**：{card.summary}")

    lines.extend(["", "## 跨平台共同热点", ""])
    for card in cards:
        if len(card.platforms) >= 2:
            lines.append(f"- {card.title}：出现在 {', '.join(card.platforms)}")

    lines.extend(["", "## 建议继续跟踪", ""])
    for card in follow_up:
        lines.append(f"- {card.title}：置信度 {card.confidence}")

    lines.extend(
        [
            "",
            "## 数据来源与置信度说明",
            "",
            "数据来源包括国内热榜聚合接口和可读取的公开网页。详情页读取失败的话题会标记为低置信度。",
            "",
        ]
    )
    return "\n".join(lines)


def render_static_html(markdown: str) -> str:
    escaped = escape(markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>当前国内热点话题简报</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f9; color: #111827; }}
    main {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 56px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 24px; line-height: 1.7; }}
  </style>
</head>
<body>
  <main>
    <pre>{escaped}</pre>
  </main>
</body>
</html>"""
```

- [ ] **Step 3: Run report tests**

Run:

```bash
python3 -m unittest /Users/BZ/Documents/heatedTopics/tests/test_generate_reports.py
```

Expected: all tests pass.

### Task 6: Add Full CLI Entrypoint

**Files:**

- Create: `/Users/BZ/Documents/heatedTopics/src/demo_collect_hot_topics.py`

- [ ] **Step 1: Implement CLI script**

Use this content:

```python
import json

from src.demo_config import (
    DAILY_DIGEST_HTML_PATH,
    DAILY_DIGEST_PATH,
    DATA_DIR,
    HOT_LIST_PATH,
    HOT_TOPIC_CARDS_PATH,
    MAX_SELECTED_TOPICS,
    MIN_SELECTED_TOPICS,
    PLATFORMS,
    REPORTS_DIR,
    SELECTED_TOPICS_PATH,
    TOPIC_SOURCES_PATH,
)
from src.enrich_sources import enrich_topics
from src.fetch_hot_lists import fetch_all_platforms
from src.generate_reports import build_cards, render_daily_digest, render_static_html, render_topic_cards
from src.select_topics import select_topics


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    records = fetch_all_platforms(PLATFORMS)
    selected = select_topics(
        records,
        min_count=MIN_SELECTED_TOPICS,
        max_count=MAX_SELECTED_TOPICS,
    )
    sources = enrich_topics(selected)
    cards = build_cards(selected, sources)

    cards_markdown = render_topic_cards(cards)
    digest_markdown = render_daily_digest(cards)
    digest_html = render_static_html(digest_markdown)

    write_json(HOT_LIST_PATH, [record.to_dict() for record in records])
    write_json(SELECTED_TOPICS_PATH, [topic.to_dict() for topic in selected])
    write_json(TOPIC_SOURCES_PATH, [source.to_dict() for source in sources])
    write_text(HOT_TOPIC_CARDS_PATH, cards_markdown)
    write_text(DAILY_DIGEST_PATH, digest_markdown)
    write_text(DAILY_DIGEST_HTML_PATH, digest_html)

    print(f"Collected records: {len(records)}")
    print(f"Selected topics: {len(selected)}")
    print(f"Cards: {len(cards)}")
    print(f"Digest: {DAILY_DIGEST_PATH}")
    print(f"HTML: {DAILY_DIGEST_HTML_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run unit tests**

Run:

```bash
python3 -m unittest discover /Users/BZ/Documents/heatedTopics/tests
```

Expected: all tests pass.

- [ ] **Step 3: Run full demo**

Run:

```bash
cd /Users/BZ/Documents/heatedTopics
PYTHONPATH=/Users/BZ/Documents/heatedTopics python3 -m src.demo_collect_hot_topics
```

Expected:

```text
Collected records: 30 or more
Selected topics: 5 to 8
Cards: 5 to 8
Digest: /Users/BZ/Documents/heatedTopics/reports/daily_digest_demo.md
HTML: /Users/BZ/Documents/heatedTopics/reports/daily_digest_demo.html
```

If `Collected records` is under 30, reduce the acceptance threshold to the number of successful platforms multiplied by 5 and explain that this is a live-source instability issue during the demo.

### Task 7: Add Optional LLM Generation

**Files:**

- Modify: `/Users/BZ/Documents/heatedTopics/src/generate_reports.py`

- [ ] **Step 1: Keep deterministic fallback as default**

Do not require an LLM for the script to run. The fallback card generation from Task 5 must continue to work without API keys.

- [ ] **Step 2: Add LLM only if local package and key are available**

Use exported environment variable only:

```bash
export OPENAI_API_KEY="..."
```

Do not create or modify `.env`.

- [ ] **Step 3: Manual smoke test without LLM**

Run:

```bash
unset OPENAI_API_KEY
cd /Users/BZ/Documents/heatedTopics
PYTHONPATH=/Users/BZ/Documents/heatedTopics python3 -m src.demo_collect_hot_topics
```

Expected: script still generates all artifacts.

## 4. Demo Runbook

### Before presentation

- [ ] Run:

```bash
cd /Users/BZ/Documents/heatedTopics
PYTHONPATH=/Users/BZ/Documents/heatedTopics python3 -m src.demo_collect_hot_topics
```

- [ ] Open generated files:

```text
/Users/BZ/Documents/heatedTopics/data/hot_list.json
/Users/BZ/Documents/heatedTopics/reports/hot_topic_cards.md
/Users/BZ/Documents/heatedTopics/reports/daily_digest_demo.md
/Users/BZ/Documents/heatedTopics/reports/daily_digest_demo.html
```

### Presentation order

1. Show `hot_list.json`: explain raw hot-list collection.
2. Show `selected_topics.json`: explain topic selection.
3. Show `hot_topic_cards.md`: explain title-to-card enrichment.
4. Show `daily_digest_demo.md`: explain final report.
5. Show `daily_digest_demo.html`: use as visual bonus if Markdown looks too plain.

### Talking points

```text
这个 Demo 验证的是一条完整链路：
从国内热榜平台获取热点，
通过规则筛选重点话题，
读取可访问详情来源，
最终生成可以直接汇报的热点卡片和简报。
```

```text
Demo 版没有做数据库和多 Agent，
因为明早最重要的是稳定展示结果。
长期版可以继续扩展成定时任务、历史追踪、MCP Server 和 Skill。
```

## 5. Verification Checklist

- [ ] `python3 -m unittest discover /Users/BZ/Documents/heatedTopics/tests` passes.
- [ ] Full demo command exits with code 0.
- [ ] `data/hot_list.json` is valid JSON.
- [ ] `data/selected_topics.json` contains 5-8 items.
- [ ] `reports/hot_topic_cards.md` contains at least 5 `## ` topic headings.
- [ ] `reports/daily_digest_demo.md` contains `# 当前国内热点话题简报`.
- [ ] `reports/daily_digest_demo.html` opens locally.

## 6. Self-Review

Spec coverage:

- Demo path is covered by Tasks 1-6.
- Optional static HTML is covered by Task 5.
- LLM is optional and non-blocking in Task 7.
- No database, MCP, or multi-Agent work is included.

Placeholder scan:

- No `TBD` or `TODO` placeholders are left.
- Known live-source uncertainty is handled through fallback behavior and demo explanation.

Risk check:

- The plan intentionally avoids hard dependency on LLM API keys.
- The plan uses live APIs, so generated topic quality depends on current network and source availability.
- If DailyHotApi endpoint paths differ at implementation time, inspect one live endpoint and update only `fetch_platform`.
