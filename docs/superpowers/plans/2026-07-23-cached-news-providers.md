# Cached News Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add anonymous, daily-cached Sina News, The Paper, and NetEase News providers with strict full-text and heat-evidence qualification, conditional keyword search, and per-platform heat ranking.

**Architecture:** Start from the `V4` workflow at commit `15965aa`, preserve its raw/normalized/detail persistence and failure isolation, then introduce a qualification layer that is the only path into formal results. Daily collection publishes eligible platform snapshots; user generation reads those snapshots, searches only when a platform has fewer than five cached matches, validates at most sixty search candidates, and returns at most twenty articles ranked by comparable platform metrics.

**Tech Stack:** Python 3.10+, `httpx`, standard-library HTML/JSON parsing, `gne>=0.4.3` as a same-HTML fallback extractor, frozen dataclasses, pytest, Markdown/JSON/TXT artifacts.

## Global Constraints

- Execute in a fresh worktree branched from `V4` commit `15965aa`; use `superpowers:using-git-worktrees` at execution time.
- Bring the approved design at commit `41ee972` and this plan commit into that worktree before production changes.
- Supported first-batch platforms are exactly `sina_news`, `thepaper`, and `netease_news`; Tencent remains deferred.
- Each platform hot board is fetched once per business day and never during a user request.
- `MIN_RESULTS = 5`, `MAX_RESULTS = 20`, `SEARCH_PAGE_SIZE = 15`, and `MAX_SEARCH_CANDIDATES = 60`.
- Search runs only when that platform has fewer than five valid cached hot-board matches.
- Formal results require full text and verified heat evidence; summary/title fallback records never become eligible.
- Search rank, result count, and recency are not heat evidence.
- Official and search-qualified records are merged and ranked by `platform_heat_score`; source order is only a tie-breaker.
- Missing metric values contribute zero and their weights are not redistributed.
- Platform failures are isolated, writes are atomic, secrets are never serialized, and no provider sends a Cookie.
- Preserve all existing V4 commands and tests while adding the new workflow.

---

## File Structure

Create or modify the following focused units:

```text
src/heated_topics_v3/
├── contracts.py                 # qualification and evidence dataclasses
├── content.py                   # deterministic container extraction and body validation
├── heat.py                      # dynamic floors, percentiles, platform scores, stable sorting
├── collection.py               # generic daily platform collection and active snapshots
├── discovery.py                # cached-board matching and conditional search orchestration
├── recommendation.py           # new three-platform generation entry point
├── storage.py                  # eligible/rejected/search-cache persistence
├── cli.py                      # collect-news and generate-news commands
└── providers/
    ├── common.py               # NewsProvider protocol and shared helpers
    ├── sina_news.py
    ├── thepaper.py
    └── netease_news.py

tests/
├── fixtures/
│   ├── sina_news_hot.txt
│   ├── sina_news_search.json
│   ├── sina_news_article.html
│   ├── sina_news_comments.json
│   ├── thepaper_hot.json
│   ├── thepaper_search.json
│   ├── thepaper_article.html
│   ├── netease_news_hot.json
│   ├── netease_news_search.html
│   └── netease_news_article.html
├── providers/
│   ├── test_sina_news.py
│   ├── test_thepaper.py
│   └── test_netease_news.py
├── test_content.py
├── test_heat.py
├── test_news_collection.py
├── test_discovery.py
├── test_news_recommendation.py
└── test_news_cli.py
```

---

### Task 1: Add Qualification Contracts and Full-Text Validation

**Files:**
- Modify: `src/heated_topics_v3/contracts.py`
- Create: `src/heated_topics_v3/content.py`
- Create: `tests/test_content.py`
- Modify: `tests/test_contracts.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: existing `HotItem` and `ItemDetail`.
- Produces: `HeatEvidence`, `ContentValidation`, `QualifiedArticle`, `extract_container_text(html, selectors)`, and `validate_full_text(content, title, summary)`.

- [ ] **Step 1: Write failing contract and validation tests**

Add tests that lock the formal-result gate:

```python
from heated_topics_v3.content import validate_full_text
from heated_topics_v3.contracts import ContentValidation, HeatEvidence, QualifiedArticle


def test_full_text_accepts_real_multi_paragraph_article():
    content = "\n\n".join(
        [
            "第一段介绍事件背景，包含明确的人物、时间和地点，并说明事件起因。",
            "第二段描述事件进展，引用公开信息并补充相关数据和各方回应。",
            "第三段交代后续安排、影响范围以及仍需继续确认的信息。",
        ]
    )
    result = validate_full_text(content, "事件标题", "事件摘要")
    assert result == ContentValidation(
        status="accepted",
        parser="",
        character_count=len("".join(content.split())),
        paragraph_count=3,
        reasons=(),
    )


def test_full_text_rejects_summary_title_and_page_chrome():
    assert validate_full_text("事件标题", "事件标题", "").status == "rejected"
    assert validate_full_text("只有一句摘要。", "事件标题", "只有一句摘要。").status == "rejected"
    chrome = ("登录后发表评论 推荐阅读 返回首页 " * 30).strip()
    result = validate_full_text(chrome, "事件标题", "")
    assert result.status == "rejected"
    assert "page_chrome" in result.reasons


def test_qualified_article_requires_full_text_and_verified_evidence(hot_item, item_detail):
    evidence = HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=1,
        native_hot_value=100.0,
        metrics={"views": 100.0},
        threshold_metrics={},
        qualified_by=("official_hot_board",),
    )
    article = QualifiedArticle(
        hot_item=hot_item,
        detail=item_detail,
        heat_evidence=evidence,
        content_validation=ContentValidation("accepted", "fixture", 300, 3, ()),
        platform_heat_score=0.0,
    )
    assert article.detail.content_status == "full_text"
```

Add local helper fixtures to `tests/test_contracts.py` using existing constructors rather than global `conftest.py`.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
uv run pytest tests/test_content.py tests/test_contracts.py -q
```

Expected: collection fails because the three dataclasses and `heated_topics_v3.content` do not exist.

- [ ] **Step 3: Add frozen contracts and deterministic validation**

Add to `contracts.py`:

```python
EvidenceSource = Literal["official_hot_board", "public_engagement"]
QualificationStatus = Literal["accepted", "rejected"]


@dataclass(frozen=True)
class HeatEvidence:
    source_kind: EvidenceSource
    platform_rank: int | None
    native_hot_value: float | None
    metrics: Mapping[str, float] = field(default_factory=dict)
    threshold_metrics: Mapping[str, float] = field(default_factory=dict)
    qualified_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentValidation:
    status: QualificationStatus
    parser: str
    character_count: int
    paragraph_count: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualifiedArticle:
    hot_item: HotItem
    detail: ItemDetail
    heat_evidence: HeatEvidence
    content_validation: ContentValidation
    platform_heat_score: float

    def __post_init__(self) -> None:
        if self.detail.content_status != "full_text":
            raise ValueError("qualified article requires full_text")
        if self.content_validation.status != "accepted":
            raise ValueError("qualified article requires accepted content")
        if not self.heat_evidence.qualified_by:
            raise ValueError("qualified article requires heat evidence")
```

Create `content.py` with:

```python
from __future__ import annotations

import re
from dataclasses import replace
from html.parser import HTMLParser

from .contracts import ContentValidation


MIN_ARTICLE_CHARACTERS = 200
_CHROME = (
    "登录", "发表评论", "推荐阅读", "相关阅读", "返回首页",
    "打开客户端", "扫码下载", "版权声明",
)


class _ContainerParser(HTMLParser):
    def __init__(self, selectors: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.selectors = selectors
        self.depth = 0
        self.ignored = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        identity = {f"#{values.get('id', '')}"}
        identity.update(f".{value}" for value in values.get("class", "").split())
        if self.depth == 0 and identity.intersection(self.selectors):
            self.depth = 1
            return
        if self.depth and tag in {"script", "style", "nav", "footer"}:
            self.ignored += 1
        elif self.depth:
            self.depth += 1

    def handle_endtag(self, tag) -> None:
        if self.ignored:
            if tag in {"script", "style", "nav", "footer"}:
                self.ignored -= 1
        elif self.depth:
            self.depth -= 1

    def handle_data(self, data) -> None:
        text = " ".join(data.split())
        if self.depth and not self.ignored and text:
            self.parts.append(text)


def extract_container_text(html: str, selectors: tuple[str, ...]) -> str:
    parser = _ContainerParser(selectors)
    parser.feed(html)
    return "\n".join(parser.parts)


def validate_full_text(
    content: str,
    title: str,
    summary: str,
    *,
    parser: str = "",
) -> ContentValidation:
    cleaned = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    compact = re.sub(r"\s+", "", cleaned)
    paragraphs = tuple(part for part in re.split(r"\n+", cleaned) if part)
    reasons: list[str] = []
    if compact in {re.sub(r"\s+", "", title), re.sub(r"\s+", "", summary)}:
        reasons.append("title_or_summary")
    if len(compact) < MIN_ARTICLE_CHARACTERS:
        reasons.append("too_short")
    sentence_count = len(re.findall(r"[。！？!?]", cleaned))
    if len(paragraphs) < 2 and sentence_count < 3:
        reasons.append("insufficient_structure")
    chrome_hits = sum(cleaned.count(value) for value in _CHROME)
    if chrome_hits >= 4:
        reasons.append("page_chrome")
    status = "rejected" if reasons else "accepted"
    return ContentValidation(
        status=status,
        parser=parser,
        character_count=len(compact),
        paragraph_count=len(paragraphs),
        reasons=tuple(reasons),
    )


def with_parser(result: ContentValidation, parser: str) -> ContentValidation:
    return replace(result, parser=parser)
```

Add `"gne>=0.4.3"` to project dependencies and run `uv lock`.

- [ ] **Step 4: Run focused and regression tests**

Run:

```powershell
uv run pytest tests/test_content.py tests/test_contracts.py -q
uv run pytest -q
```

Expected: focused tests pass and the existing V4 suite remains green.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml uv.lock src/heated_topics_v3/contracts.py src/heated_topics_v3/content.py tests/test_content.py tests/test_contracts.py
git commit -m "feat: enforce full-text qualification contracts"
```

---

### Task 2: Add Dynamic Heat Floors and Stable Platform Ranking

**Files:**
- Create: `src/heated_topics_v3/heat.py`
- Create: `tests/test_heat.py`

**Interfaces:**
- Consumes: `HeatEvidence` and `QualifiedArticle`.
- Produces: `positive_percentile(values, percentile)`, `dynamic_floors(board, absolute_floors)`, `qualifies_public_metrics(metrics, floors)`, and `rank_platform_articles(articles, weights)`.

- [ ] **Step 1: Write failing heat tests**

```python
from dataclasses import replace

from heated_topics_v3.heat import (
    dynamic_floors,
    positive_percentile,
    qualifies_public_metrics,
    rank_platform_articles,
)


def test_positive_percentile_ignores_zero_and_uses_absolute_fallback():
    assert positive_percentile([0, 10, 20, 30, 40], 0.25) == 17.5
    assert dynamic_floors(
        [{"comments": 0}, {"comments": 0}],
        {"comments": 10},
    ) == {"comments": 10.0}


def test_public_metrics_require_at_least_one_comparable_floor():
    floors = {"comments": 20.0, "likes": 50.0}
    assert qualifies_public_metrics({"comments": 21.0}, floors) == ("comments",)
    assert qualifies_public_metrics({"comments": 19.0, "views": 999.0}, floors) == ()


def test_ranking_uses_percentiles_missing_zero_and_stable_ties(qualified_articles):
    ranked = rank_platform_articles(
        qualified_articles,
        {"views": 0.45, "comments": 0.25, "likes": 0.20,
         "shares": 0.07, "collects": 0.03},
    )
    assert [item.hot_item.item_id for item in ranked] == ["high", "medium", "low"]
    assert ranked[0].platform_heat_score > ranked[1].platform_heat_score
```

Build `qualified_articles` inside the test file with three deterministic `QualifiedArticle` values; one must omit `views` to prove missing values contribute zero.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run pytest tests/test_heat.py -q
```

Expected: import error for `heated_topics_v3.heat`.

- [ ] **Step 3: Implement percentile floors and scoring**

Create `heat.py`:

```python
from __future__ import annotations

from dataclasses import replace
from math import log1p
from typing import Iterable, Mapping, Sequence

from .contracts import QualifiedArticle


def positive_percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values if float(value) > 0)
    if not ordered:
        return None
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def dynamic_floors(
    board_metrics: Iterable[Mapping[str, float]],
    absolute_floors: Mapping[str, float],
) -> dict[str, float]:
    rows = tuple(board_metrics)
    result: dict[str, float] = {}
    for metric, fallback in absolute_floors.items():
        calculated = positive_percentile(
            (row.get(metric, 0.0) for row in rows),
            0.25,
        )
        result[metric] = float(fallback if calculated is None else calculated)
    return result


def qualifies_public_metrics(
    metrics: Mapping[str, float],
    floors: Mapping[str, float],
) -> tuple[str, ...]:
    return tuple(
        metric
        for metric, floor in floors.items()
        if float(metrics.get(metric, 0.0)) >= float(floor)
    )


def _percentiles(values: Sequence[float]) -> tuple[float, ...]:
    transformed = [log1p(max(0.0, value)) for value in values]
    ordered = sorted(set(transformed))
    if len(ordered) <= 1:
        return tuple(1.0 if value > 0 else 0.0 for value in transformed)
    return tuple(
        0.0 if value == 0 else ordered.index(value) / (len(ordered) - 1)
        for value in transformed
    )


def rank_platform_articles(
    articles: Sequence[QualifiedArticle],
    weights: Mapping[str, float],
) -> tuple[QualifiedArticle, ...]:
    items = tuple(articles)
    metric_percentiles = {
        metric: _percentiles(
            tuple(float(item.heat_evidence.metrics.get(metric, 0.0)) for item in items)
        )
        for metric in weights
    }
    scored = tuple(
        replace(
            item,
            platform_heat_score=sum(
                weight * metric_percentiles[metric][index]
                for metric, weight in weights.items()
            ),
        )
        for index, item in enumerate(items)
    )
    ordered = sorted(scored, key=lambda item: item.hot_item.item_id)
    ordered.sort(
        key=lambda item: item.hot_item.publication_time or "",
        reverse=True,
    )
    ordered.sort(key=lambda item: item.heat_evidence.platform_rank or 10**9)
    ordered.sort(
        key=lambda item: item.heat_evidence.source_kind != "official_hot_board"
    )
    ordered.sort(
        key=lambda item: len(tuple(
            value
            for value in item.heat_evidence.metrics.values()
            if value > 0
        )),
        reverse=True,
    )
    ordered.sort(key=lambda item: item.platform_heat_score, reverse=True)
    return tuple(ordered)
```

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
uv run pytest tests/test_heat.py -q
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/heat.py tests/test_heat.py
git commit -m "feat: rank platform articles by verified heat"
```

---

### Task 3: Extend Storage for Eligible Snapshots and Search Cache

**Files:**
- Modify: `src/heated_topics_v3/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Consumes: `QualifiedArticle`, rejected-record mappings, normalized keywords.
- Produces: `save_eligible`, `load_eligible`, `save_rejected`, `save_stable_detail`, `search_cache_dir`, `save_search_cache`, `load_search_cache`, `publish_active_snapshot`, `resolve_eligible_snapshot`, and isolated news-result persistence.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_eligible_and_rejected_are_separate(tmp_path, qualified_article):
    repository = FileRepository(tmp_path)
    repository.save_eligible("2026-07-23", "sina_news", (qualified_article,))
    repository.save_rejected(
        "2026-07-23",
        "sina_news",
        ({"item_id": "bad", "reasons": ["too_short"]},),
    )
    loaded = repository.load_eligible("2026-07-23", "sina_news")
    assert [item.hot_item.item_id for item in loaded] == [
        qualified_article.hot_item.item_id
    ]
    rejected = repository._read_json(
        tmp_path / "daily_hot_lists/2026-07-23/rejected/sina_news.json"
    )
    assert rejected == [{"item_id": "bad", "reasons": ["too_short"]}]


def test_search_cache_hashes_keyword_and_distinguishes_empty_from_failure(
    tmp_path, qualified_article
):
    repository = FileRepository(tmp_path)
    repository.save_search_cache(
        "2026-07-23",
        "thepaper",
        " 人工智能 ",
        status="success",
        articles=(qualified_article,),
        rejected=(),
    )
    cache = repository.load_search_cache("2026-07-23", "thepaper", "人工智能")
    assert cache.status == "success"
    assert cache.articles == (qualified_article,)
    assert "人工智能" not in str(repository.search_cache_dir(
        "2026-07-23", "thepaper", "人工智能"
    ))


def test_news_results_do_not_collide_with_existing_v1_results(tmp_path):
    repository = FileRepository(tmp_path)
    assert repository.news_user_dir("u1") == tmp_path / "news_user_results/u1"
    assert repository.user_dir("u1") == tmp_path / "user_results/u1"


def test_active_snapshot_resolves_at_most_forty_eight_hours_old(
    tmp_path, qualified_article
):
    repository = FileRepository(tmp_path)
    repository.save_eligible("2026-07-22", "sina_news", (qualified_article,))
    repository.publish_active_snapshot("sina_news", "2026-07-22")
    resolved = repository.resolve_eligible_snapshot(
        "sina_news", "2026-07-23T12:00:00+08:00", max_age_hours=48
    )
    assert resolved is not None
    assert resolved[0] == "2026-07-22"
    assert repository.resolve_eligible_snapshot(
        "sina_news", "2026-07-25T12:01:00+08:00", max_age_hours=48
    ) is None
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/test_storage.py -q
```

Expected: `FileRepository` lacks the new methods.

- [ ] **Step 3: Implement JSON-safe qualification persistence**

Add a frozen `SearchCacheRecord` to `contracts.py`:

```python
@dataclass(frozen=True)
class SearchCacheRecord:
    status: Literal["success", "empty", "failed"]
    business_date: str
    platform: str
    normalized_keyword: str
    collected_at: str
    articles: tuple[QualifiedArticle, ...] = ()
    rejected: tuple[Mapping[str, Any], ...] = ()
    retry_after: str | None = None
```

Add storage paths and methods:

```python
def save_eligible(self, business_date, platform, articles):
    return self.write_json(
        self.daily_dir(business_date) / "eligible" / f"{platform}.json",
        tuple(articles),
    )


def save_rejected(self, business_date, platform, rejected):
    return self.write_json(
        self.daily_dir(business_date) / "rejected" / f"{platform}.json",
        tuple(rejected),
    )


def search_cache_dir(self, business_date, platform, keyword):
    normalized = " ".join(normalize("NFKC", keyword).casefold().split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return self.root / "search_cache" / _date_text(business_date) / platform / digest
```

Implement explicit `_heat_evidence`, `_content_validation`, `_qualified_article`, and `_search_cache_record` deserializers matching Task 1 field names. Do not use dynamic class construction.

Implement active snapshots as an atomic JSON pointer:

```python
def publish_active_snapshot(self, platform: str, business_date: str) -> Path:
    target = self.root / "active_snapshots" / f"{platform}.json"
    temporary = target.with_suffix(".tmp")
    self.write_json(temporary, {"business_date": business_date})
    temporary.replace(target)
    return target
```

Add stable detail and isolated news-result paths:

```python
def save_stable_detail(
    self, business_date: BusinessDate, platform: str, item_id: str, content: str
) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item_id)
    path = self.daily_dir(business_date) / "details" / f"{platform}_{safe_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def news_user_dir(self, user_id: str) -> Path:
    validate_user_id(user_id)
    return self.root / "news_user_results" / user_id
```

Implement `load_news_user_bundle` and `write_news_user_result_atomic` with the
same containment, file-lock, fsync, and atomic-rename behavior as the existing
V1 methods, but rooted under `news_user_results`.

Implement `resolve_eligible_snapshot` by reading the active pointer, parsing the
requested timestamp and snapshot business date in `Asia/Shanghai`, rejecting a
negative age or an age greater than `max_age_hours`, and returning:

```python
tuple[str, tuple[QualifiedArticle, ...]] | None
```

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
uv run pytest tests/test_storage.py -q
uv run pytest -q
```

Expected: new persistence tests and existing path-containment tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/contracts.py src/heated_topics_v3/storage.py tests/test_storage.py
git commit -m "feat: persist qualified news and search caches"
```

---

### Task 4: Implement the Sina News Provider

**Files:**
- Create: `src/heated_topics_v3/providers/sina_news.py`
- Modify: `src/heated_topics_v3/providers/__init__.py`
- Modify: `tests/test_contracts.py`
- Create: `tests/providers/test_sina_news.py`
- Create: `tests/fixtures/sina_news_hot.txt`
- Create: `tests/fixtures/sina_news_search.json`
- Create: `tests/fixtures/sina_news_article.html`
- Create: `tests/fixtures/sina_news_comments.json`

**Interfaces:**
- Produces: `SinaNewsProvider.collect_hot_list`, `search`, `fetch_detail`, and `enrich_metrics`.
- Endpoint contracts: JSONP hot list, JSON search envelope, article HTML, and public comment JSON.

- [ ] **Step 1: Save sanitized real fixtures and write failing parser tests**

Tests must prove:

```python
def test_hot_list_preserves_top_num_rank_and_comment_identity(fixtures):
    items = SinaNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items[0].platform == "sina_news"
    assert items[0].rank == 1
    assert items[0].heat.metrics["top_num"] == 15558
    assert items[0].raw_payload["commentid"]


def test_search_count_is_not_heat(fixtures):
    items = SinaNewsProvider.parse_search(fixtures["search"], NOW)
    assert items
    assert all(item.heat.value is None for item in items)
    assert all("search_rank" not in item.heat.metrics for item in items)


def test_article_requires_validated_full_text(fixtures, client):
    detail = SinaNewsProvider(client).fetch_detail(HOT_ITEM, NOW)
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"


def test_short_article_is_rejected_not_summary_fallback(client):
    detail = SinaNewsProvider(client).fetch_detail(HOT_ITEM, NOW)
    assert detail.content == ""
    assert detail.content_status == "rejected"
    assert detail.fetch_status == "rejected:too_short"
```

Extend `ContentStatus` to include `"rejected"` before constructing the last
result, and update the exact literal assertion in `tests/test_contracts.py` to:

```python
assert get_args(ContentStatus) == (
    "full_text", "summary", "title_only", "rejected"
)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_sina_news.py -q
```

Expected: provider module is missing.

- [ ] **Step 3: Implement strict Sina endpoint parsing**

Use constants:

```python
SINA_HOT_URL = (
    "https://top.news.sina.com.cn/ws/GetTopDataList.php"
    "?js_var=data&top_cat=www_www_all_suda_suda&top_channel=news"
    "&top_order=DESC&top_show_num=50&top_time=today&top_type=day"
)
SINA_SEARCH_URL = "https://search.sina.com.cn/api/news"
SINA_COMMENT_URL = "https://comment5.news.sina.com.cn/page/info"
SINA_SELECTORS = (
    "#artibody", "#article", ".article-content", "#article-content",
    ".article-content-left", ".main-content",
)
SINA_WEIGHTS = {"top_num": 0.70, "comments": 0.30}
SINA_ABSOLUTE_FLOORS = {"comments": 10.0}
```

Implement JSONP parsing with one anchored expression, reject missing/non-list `data`, normalize comma-formatted `top_num`, and retain `commentid`.

Implement `search` with `q` and `page`; never assign heat from response count or result position.

Implement detail extraction with source selectors first and GNE second:

```python
content = extract_container_text(response.text, SINA_SELECTORS)
parser = "sina_dom"
if validate_full_text(content, item.title, item.summary).status != "accepted":
    extracted = GeneralNewsExtractor().extract(response.text)
    content = str(extracted.get("content") or "")
    parser = "gne"
validation = validate_full_text(content, item.title, item.summary, parser=parser)
if validation.status != "accepted":
    return ItemDetail(item.item_id, "", "rejected", item.publication_time,
                      collected_at, item.url,
                      f"rejected:{','.join(validation.reasons)}")
return ItemDetail(item.item_id, content, "full_text", item.publication_time,
                  collected_at, item.url, "success")
```

Implement `enrich_metrics` by splitting `commentid` into channel/news ID, fetching the public comment envelope, and adding `comments=result.count.total`. A missing or malformed comment response leaves comments absent; it never invents zero.

- [ ] **Step 4: Run provider and full tests**

Run:

```powershell
uv run pytest tests/providers/test_sina_news.py -q
uv run pytest -q
```

Expected: provider tests pass; no existing Toutiao behavior changes yet.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/contracts.py src/heated_topics_v3/providers/sina_news.py src/heated_topics_v3/providers/__init__.py tests/test_contracts.py tests/providers/test_sina_news.py tests/fixtures/sina_news_*
git commit -m "feat: add strict sina news provider"
```

---

### Task 5: Implement The Paper Provider

**Files:**
- Create: `src/heated_topics_v3/providers/thepaper.py`
- Modify: `src/heated_topics_v3/providers/__init__.py`
- Create: `tests/providers/test_thepaper.py`
- Create: `tests/fixtures/thepaper_hot.json`
- Create: `tests/fixtures/thepaper_search.json`
- Create: `tests/fixtures/thepaper_article.html`

**Interfaces:**
- Produces: `ThePaperProvider.collect_hot_list`, `search`, `fetch_detail`, and `enrich_metrics`.

- [ ] **Step 1: Write failing fixture-based tests**

```python
def test_hot_list_keeps_interaction_praise_and_article_constraints(fixtures):
    items = ThePaperProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items
    assert all(item.raw_payload["contType"] == 0 for item in items)
    assert items[0].heat.metrics == {
        "interaction_num": 15,
        "praise_times": 396,
    }


def test_search_sends_exact_anonymous_contract(mock_transport):
    capture = ThePaperProvider(client).search("人工智能", 1, 15, NOW)
    request = mock_transport.requests[0]
    assert request.headers["client-type"] == "1"
    assert request.json() == {
        "word": "人工智能", "orderType": 3, "pageNum": 1,
        "pageSize": 15, "searchType": 1,
    }
    assert capture.items


def test_next_data_yields_full_text_and_paywall_is_rejected(fixtures):
    detail = provider.fetch_detail(ARTICLE, NOW)
    assert detail.content_status == "full_text"
    assert "正文第一段" in detail.content
```

Include fixture rows for `contType != 0`, `paywalled=true`, an external forward, and empty content; assert each is excluded or rejected.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_thepaper.py -q
```

Expected: missing provider module.

- [ ] **Step 3: Implement The Paper**

Use:

```python
THEPAPER_HOT_URL = "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"
THEPAPER_SEARCH_URL = "https://api.thepaper.cn/search/web/news"
THEPAPER_ARTICLE_URL = "https://www.thepaper.cn/newsDetail_forward_{cont_id}"
THEPAPER_WEIGHTS = {"interaction_num": 0.60, "praise_times": 0.40}
THEPAPER_ABSOLUTE_FLOORS = {
    "interaction_num": 1.0,
    "praise_times": 10.0,
}
```

Parse `data.hotNews`, retain only article/non-paywalled/internal rows, strip `<font>` search highlighting, and preserve both numeric metrics.

Extract the `script#__NEXT_DATA__` JSON object with a small HTML parser that captures only that script. Resolve:

```python
payload["props"]["pageProps"]["detailData"]["contentDetail"]["content"]
```

Convert HTML content to paragraph text with the shared container/text helper, then apply `validate_full_text`. GNE is the second parser only when structured content fails.

`enrich_metrics` is a no-op that returns the input tuple because hot and search responses already include both comparable metrics.

- [ ] **Step 4: Run provider and full tests**

Run:

```powershell
uv run pytest tests/providers/test_thepaper.py -q
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/providers/thepaper.py src/heated_topics_v3/providers/__init__.py tests/providers/test_thepaper.py tests/fixtures/thepaper_*
git commit -m "feat: add strict thepaper provider"
```

---

### Task 6: Implement the NetEase News Provider

**Files:**
- Create: `src/heated_topics_v3/providers/netease_news.py`
- Modify: `src/heated_topics_v3/providers/__init__.py`
- Create: `tests/providers/test_netease_news.py`
- Create: `tests/fixtures/netease_news_hot.json`
- Create: `tests/fixtures/netease_news_search.html`
- Create: `tests/fixtures/netease_news_article.html`

**Interfaces:**
- Produces: `NeteaseNewsProvider.collect_hot_list`, `search`, `fetch_detail`, and `enrich_metrics`.

- [ ] **Step 1: Write failing provider tests**

```python
def test_uses_rich_hot_endpoint_and_preserves_all_metrics(fixtures):
    items = NeteaseNewsProvider.parse_hot_list(fixtures["hot"], NOW)
    assert items[0].heat.metrics == {
        "hot_value": 2478683,
        "click": 835915,
        "comments": 74959,
        "votes": 65567,
        "thread_votes": 1436,
    }
    assert all(item.raw_payload["type"] == "doc" for item in items)


def test_search_html_returns_fifty_candidates_without_treating_order_as_heat(fixtures):
    items = NeteaseNewsProvider.parse_search(fixtures["search"], NOW)
    assert len(items) == 50
    assert items[0].heat.metrics == {"comments": 2}
    assert items[0].heat.metric_name == "public_engagement"


def test_post_body_is_full_text_and_non_doc_is_rejected(fixtures):
    detail = provider.fetch_detail(ARTICLE, NOW)
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"
```

Include search rows with zero comments, duplicate `docid`, malformed URL, video URL, and highlighted `<em>` keywords; assert normalization and filtering.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_netease_news.py -q
```

Expected: missing provider module.

- [ ] **Step 3: Implement the rich NetEase contracts**

Use:

```python
NETEASE_HOT_URL = (
    "https://gw.m.163.com/nc-main/api/v1/hqc/no-repeat-hot-list"
)
NETEASE_SEARCH_URL = "https://www.163.com/search"
NETEASE_ARTICLE_URL = "https://www.163.com/dy/article/{docid}.html"
NETEASE_SELECTORS = (".post_body", "#endText", ".post_text")
NETEASE_WEIGHTS = {
    "hot_value": 0.40,
    "click": 0.30,
    "comments": 0.15,
    "votes": 0.10,
    "thread_votes": 0.05,
}
NETEASE_ABSOLUTE_FLOORS = {"comments": 10.0}
```

Validate `code == 0`, `data.items` is a nonempty list, and retain only `type == "doc"`.

Implement a dedicated HTML parser for `.keyword_new` search cards that extracts the `<h3>` URL/title, source, time, and visible comment count. Derive `docid` only from canonical NetEase article URLs. Search order is stored as diagnostic `rank` but not inserted into heat metrics.

Extract `.post_body` first, then legacy containers, then GNE. Apply the common hard gate and return empty rejected detail on failure.

`enrich_metrics` keeps search-page comments and can refresh them from the public comment page when the parsed count is absent; it must not invent absent `hotValue` or click data.

- [ ] **Step 4: Run provider and full tests**

Run:

```powershell
uv run pytest tests/providers/test_netease_news.py -q
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/providers/netease_news.py src/heated_topics_v3/providers/__init__.py tests/providers/test_netease_news.py tests/fixtures/netease_news_*
git commit -m "feat: add strict netease news provider"
```

---

### Task 7: Generalize Daily Collection and Publish Eligible Snapshots

**Files:**
- Modify: `src/heated_topics_v3/providers/common.py`
- Modify: `src/heated_topics_v3/collection.py`
- Create: `tests/test_news_collection.py`

**Interfaces:**
- Produces: `NewsProvider` protocol and `collect_news_daily(now, repository, providers)`.
- Consumes: provider captures, `fetch_detail`, `enrich_metrics`, common validation, heat evidence, and storage methods.

- [ ] **Step 1: Write failing collection tests**

Use fake providers to assert:

```python
def test_daily_collection_publishes_only_full_text_with_heat(tmp_path):
    repository = FileRepository(tmp_path)
    snapshot = collect_news_daily(NOW, repository, PROVIDERS)
    assert snapshot.platform_statuses[0].status == "partial"
    eligible = repository.load_eligible("2026-07-23", "sina_news")
    assert [item.hot_item.item_id for item in eligible] == ["full"]
    rejected = repository._read_json(
        repository.daily_dir("2026-07-23") / "rejected/sina_news.json"
    )
    assert {item["item_id"] for item in rejected} == {"short", "no_metric"}


def test_collection_fetches_each_board_once_and_isolates_platform_failure(tmp_path):
    collect_news_daily(NOW, repository, providers)
    assert providers["sina_news"].hot_calls == 1
    assert providers["thepaper"].hot_calls == 1
    assert providers["netease_news"].hot_calls == 1
    assert statuses["thepaper"].status == "failed"
    assert statuses["sina_news"].status == "success"
```

Also assert details use stable item IDs, no summary/title fallback file is written, and active snapshot updates only after eligible/rejected files exist.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/test_news_collection.py -q
```

Expected: missing `collect_news_daily` and `NewsProvider`.

- [ ] **Step 3: Implement generic provider protocol and collector**

Add to `providers/common.py`:

```python
class NewsProvider(Protocol):
    platform: str
    weights: Mapping[str, float]
    absolute_floors: Mapping[str, float]

    def collect_hot_list(self, collected_at: str) -> ProviderCapture: ...
    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail: ...
    def search(
        self, keyword: str, page: int, page_size: int, collected_at: str
    ) -> ProviderCapture: ...
    def enrich_metrics(
        self, items: Sequence[HotItem], collected_at: str
    ) -> tuple[HotItem, ...]: ...
```

Add:

```python
NEWS_PLATFORMS = ("sina_news", "thepaper", "netease_news")
```

Implement `collect_news_daily` separately from `collect_v1_daily` to avoid regressing V4:

1. Call each board exactly once.
2. Save raw and normalized before details.
3. Enrich hot-board metrics.
4. Compute floors from the enriched official board.
5. Fetch details with at most three workers per platform.
6. Construct `HeatEvidence(source_kind="official_hot_board", ...)`.
7. Construct `QualifiedArticle` only for accepted full text.
8. Save eligible/rejected and collection status.
9. Publish that platform active snapshot last.

Represent rejected rows with fixed safe fields:

```python
{
    "item_id": item.item_id,
    "source_url": item.url,
    "reasons": list(validation.reasons or (detail.fetch_status,)),
}
```

- [ ] **Step 4: Run collection and regression tests**

Run:

```powershell
uv run pytest tests/test_news_collection.py tests/test_collection.py -q
uv run pytest -q
```

Expected: both old V1 and new news collectors pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/providers/common.py src/heated_topics_v3/collection.py tests/test_news_collection.py
git commit -m "feat: publish qualified daily news snapshots"
```

---

### Task 8: Add Conditional Search Discovery, Deduplication, and Search Cache

**Files:**
- Create: `src/heated_topics_v3/discovery.py`
- Create: `tests/test_discovery.py`

**Interfaces:**
- Produces: `discover_platform_articles(profile, business_date, collected_at, repository, provider)`.
- Guarantees: no search at five cached matches, at most sixty unique search candidates, full-text/evidence qualification, platform deduplication, heat ranking, and a twenty-result cap.

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_five_cached_matches_skip_search(repository, provider, profile):
    seed_eligible(repository, "sina_news", count=5)
    result = discover_platform_articles(
        profile, "2026-07-23", NOW, repository, provider
    )
    assert len(result) == 5
    assert provider.search_calls == []


def test_four_matches_search_until_twenty_or_sixty_candidates(
    repository, provider, profile
):
    seed_eligible(repository, "thepaper", count=4)
    provider.pages = make_pages(total=60, qualified=18)
    result = discover_platform_articles(
        profile, "2026-07-23", NOW, repository, provider
    )
    assert len(result) == 20
    assert sum(len(page) for page in provider.search_calls) <= 60
    assert result == tuple(sorted(
        result, key=lambda item: item.platform_heat_score, reverse=True
    ))


def test_search_results_without_body_or_heat_are_rejected_and_cached(
    repository, provider, profile
):
    result = discover_platform_articles(
        profile, "2026-07-23", NOW, repository, provider
    )
    assert all(item.detail.content_status == "full_text" for item in result)
    assert all(item.heat_evidence.qualified_by for item in result)
    second = discover_platform_articles(
        profile, "2026-07-23", NOW, repository, provider
    )
    assert second == result
    assert provider.search_call_count == 1
```

Add tests for ID/URL/title deduplication, explicit empty cache, transient failure not becoming empty, and existing hot-board evidence surviving a duplicate search row.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/test_discovery.py -q
```

Expected: missing discovery module.

- [ ] **Step 3: Implement the bounded discovery algorithm**

Define:

```python
MIN_RESULTS = 5
MAX_RESULTS = 20
SEARCH_PAGE_SIZE = 15
MAX_SEARCH_CANDIDATES = 60
```

Use the existing NFKC matching semantics over title, summary, and full detail. Load only `eligible` cached board records.

When fewer than five match:

1. Resolve the requested platform snapshot through `resolve_eligible_snapshot`
   with a 48-hour maximum age, retaining `snapshot_date` and `is_stale`.
2. Reuse a successful or explicit-empty search cache.
3. Otherwise request pages until no next data, 60 unique candidates, or 20 qualified total.
4. Perform title/summary keyword prefilter before detail calls.
5. Enrich metrics.
6. Require `qualifies_public_metrics(...)` or official overlap.
7. Fetch and validate full detail.
8. Persist eligible and rejected search records.
9. Merge by ID, canonical URL, then normalized title.
10. For duplicates, preserve official evidence, minimum official rank, maximum same-name metrics, and accepted full text.
11. Rank with the provider weights and return the first twenty.

Use a fixed negative-cache duration of ten minutes for transient failures. Store `retry_after` as an ISO timestamp, and retry after it expires.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
uv run pytest tests/test_discovery.py -q
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/discovery.py tests/test_discovery.py
git commit -m "feat: add bounded cached news discovery"
```

---

### Task 9: Add Three-Platform Recommendation and CLI Commands

**Files:**
- Modify: `src/heated_topics_v3/recommendation.py`
- Modify: `src/heated_topics_v3/reporting.py`
- Modify: `src/heated_topics_v3/cli.py`
- Modify: `src/heated_topics_v3/__init__.py`
- Create: `tests/test_news_recommendation.py`
- Create: `tests/test_news_cli.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `generate_news_user_result`, `heated-topics collect-news`, and `heated-topics generate-news`.

- [ ] **Step 1: Write failing recommendation and CLI tests**

```python
def test_news_generation_returns_each_platform_independently(
    repository, profile, providers
):
    bundle = generate_news_user_result(
        profile, NOW, repository, providers
    )
    assert bundle.status == "generated"
    assert bundle.query_metadata["platforms"]["sina_news"]["count"] <= 20
    assert bundle.query_metadata["platforms"]["thepaper"]["count"] <= 20
    assert bundle.query_metadata["platforms"]["netease_news"]["count"] <= 20
    assert all(
        item.content_status == "full_text"
        for item in bundle.recommendations
    )


def test_collect_news_cli_does_not_send_cookie(monkeypatch, capsys):
    code = main(["collect-news", "--data-root", "data"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["command"] == "collect-news"
    assert payload["platforms"] == ["sina_news", "thepaper", "netease_news"]
    assert all("cookie" not in key.casefold() for key in CAPTURED_HEADERS)


def test_generate_news_reuses_same_day_result_without_search(tmp_path):
    first = main([
        "generate-news", "--data-root", str(tmp_path),
        "--profile", "config/profiles/tech_ai_creator.json",
    ])
    second = main([
        "generate-news", "--data-root", str(tmp_path),
        "--profile", "config/profiles/tech_ai_creator.json",
    ])
    assert first == 0
    assert second == 0
    assert SEARCH_CALLS_AFTER_SECOND == SEARCH_CALLS_AFTER_FIRST
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/test_news_recommendation.py tests/test_news_cli.py -q
```

Expected: new entry points and commands are absent.

- [ ] **Step 3: Implement generation and CLI wiring**

Add:

```python
def generate_news_user_result(
    profile: UserProfile,
    now: datetime,
    repository: FileRepository,
    providers: Mapping[str, NewsProvider],
) -> RecommendationBundle:
```

Reuse the existing locking algorithm but persist through the isolated
`news_user_results` methods from Task 3, so a same-day V1 result cannot suppress
or overwrite a three-platform news result. Call `discover_platform_articles` in
fixed display order:

```python
("sina_news", "thepaper", "netease_news")
```

Convert only `QualifiedArticle` values into `RecommendationItem`, preserving all evidence metrics and `platform_heat_score`. Do not populate `potential_topics` or `general_fallback`.

Add parser subcommands:

```text
heated-topics collect-news --data-root data
heated-topics generate-news --data-root data --profile config/profiles/tech_ai_creator.json
```

Construct one shared anonymous `httpx.Client` with User-Agent, timeout, and redirect policy only. Never add Cookie, Authorization, `.env`, or API keys.

Document commands, data layout, result limits, strict full-text behavior, and deferred Tencent scope in `README.md`.

- [ ] **Step 4: Run focused, full, and compile verification**

Run:

```powershell
uv run pytest tests/test_news_recommendation.py tests/test_news_cli.py -q
uv run pytest -q
uv run python -m compileall -q src tests
git diff --check
```

Expected: all tests pass, compile exits 0, and diff check has no errors.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/recommendation.py src/heated_topics_v3/reporting.py src/heated_topics_v3/cli.py src/heated_topics_v3/__init__.py tests/test_news_recommendation.py tests/test_news_cli.py README.md
git commit -m "feat: deliver cached news recommendation workflow"
```

---

### Task 10: Run Real Anonymous Smoke Tests and Record Evidence

**Files:**
- Create: `docs/specs/cached-news-providers-implementation-report.md`
- Create: `config/profiles/news_smoke_common.json`
- Create: `config/profiles/news_smoke_ai.json`
- Create: `tools/validate_news_smoke.py`
- Create under ignored/local smoke root: raw, normalized, eligible, rejected, detail, search-cache, and result artifacts.

**Interfaces:**
- Verifies the complete production entry points against current public endpoints without persisting credentials.

- [ ] **Step 1: Run daily collection twice in a disposable data root**

Run:

```powershell
$smokeRoot = Join-Path $env:TEMP 'heatedtopics-news-smoke-20260723'
uv run heated-topics collect-news --data-root $smokeRoot
uv run heated-topics collect-news --data-root $smokeRoot
```

Expected:

- Both commands emit one JSON object.
- Each platform records raw, normalized, eligible, rejected, and status files.
- The second run reuses stable detail files where item IDs match.
- No platform request contains Cookie or Authorization.

- [ ] **Step 2: Add exact smoke profiles and exercise both branches**

Create `config/profiles/news_smoke_common.json`:

```json
{
  "user_id": "news-smoke-common",
  "primary_track": "综合新闻",
  "secondary_track": "热榜",
  "persona": "验证缓存热榜分支",
  "primary_keyword": "的",
  "updated_at": "2026-07-23T00:00:00+08:00"
}
```

Create `config/profiles/news_smoke_ai.json`:

```json
{
  "user_id": "news-smoke-ai",
  "primary_track": "人工智能",
  "secondary_track": "产业新闻",
  "persona": "验证搜索补足分支",
  "primary_keyword": "人工智能",
  "updated_at": "2026-07-23T00:00:00+08:00"
}
```

Run both profiles twice:

```powershell
uv run heated-topics generate-news --data-root $smokeRoot --profile config/profiles/news_smoke_common.json
uv run heated-topics generate-news --data-root $smokeRoot --profile config/profiles/news_smoke_common.json
uv run heated-topics generate-news --data-root $smokeRoot --profile config/profiles/news_smoke_ai.json
uv run heated-topics generate-news --data-root $smokeRoot --profile config/profiles/news_smoke_ai.json
```

Expected:

- The common-keyword profile has at least five cached matches on each platform
  whose eligible board contains five articles and therefore issues no search.
- The AI profile searches only platforms with fewer than five cached matches.
- Each first call is `generated` or truthful `no_result`.
- Each second call is `existing` and issues no new search request.

- [ ] **Step 3: Add and run an exact smoke validator**

Create `tools/validate_news_smoke.py`:

```python
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


SECRET = re.compile(
    r"(?i)(authorization|cookie|api[_-]?key|token|secret)\s*[:=]\s*"
    r"(?!null\b|none\b|false\b|true\b|0\b)[\"']?[^\"'\s,}]{8,}"
)


def main(root_text: str) -> int:
    root = Path(root_text)
    violations: list[str] = []
    rejected_ids: set[str] = set()
    eligible_ids: set[str] = set()

    for path in root.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        if SECRET.search(text):
            violations.append(f"credential:{path}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            violations.append(f"json:{path}")
            continue
        if "/rejected/" in path.as_posix():
            rejected_ids.update(
                str(row.get("item_id"))
                for row in payload
                if isinstance(row, dict) and row.get("item_id")
            )
        if "/eligible/" in path.as_posix():
            eligible_ids.update(
                str(row.get("hot_item", {}).get("item_id"))
                for row in payload
                if isinstance(row, dict)
            )
        if path.name != "result.json":
            continue
        by_platform: dict[str, list[float]] = defaultdict(list)
        for row in payload.get("recommendations", []):
            if row.get("content_status") != "full_text" or not row.get("detail"):
                violations.append(f"content:{path}:{row.get('hot_item_id')}")
            evidence = row.get("evidence", {})
            if not evidence.get("qualified_by") or not evidence.get("metrics"):
                violations.append(f"evidence:{path}:{row.get('hot_item_id')}")
            by_platform[str(row.get("platform"))].append(
                float(evidence.get("platform_heat_score", 0.0))
            )
        for platform, scores in by_platform.items():
            if len(scores) > 20:
                violations.append(f"limit:{path}:{platform}")
            if scores != sorted(scores, reverse=True):
                violations.append(f"order:{path}:{platform}")

    overlap = rejected_ids.intersection(eligible_ids)
    if overlap:
        violations.append(f"rejected-eligible-overlap:{sorted(overlap)}")
    if violations:
        print(json.dumps({"status": "failed", "violations": violations},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"status": "success", "violations": []},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
```

Run:

```powershell
uv run python tools/validate_news_smoke.py $smokeRoot
```

Expected: zero contract violations and zero credential-shaped values.

- [ ] **Step 4: Record measured results**

Write `docs/specs/cached-news-providers-implementation-report.md` with:

- Exact commit and timestamp.
- Per-platform raw, normalized, eligible, and rejected counts.
- Detail success rates and top rejection reasons.
- Search pages/candidates/qualified counts for the search branch.
- Cache-reuse evidence.
- Endpoint/schema deviations encountered.
- Test, compile, diff-check, and credential-scan outputs.
- Paths to local smoke artifacts without committing collected copyrighted article bodies.

- [ ] **Step 5: Run final verification and commit the report**

Run:

```powershell
uv run pytest -q
uv run python -m compileall -q src tests
git diff --check
git status --short
```

Expected: all tests pass, compile and diff check exit 0, and only the implementation report is uncommitted.

Commit:

```powershell
git add docs/specs/cached-news-providers-implementation-report.md config/profiles/news_smoke_common.json config/profiles/news_smoke_ai.json tools/validate_news_smoke.py
git commit -m "docs: verify cached news providers"
```

---

## Final Verification Checklist

- [ ] Implementation branch is based on `V4` commit `15965aa` and contains the approved design.
- [ ] Existing V4 Toutiao/Juejin tests remain green.
- [ ] Sina, The Paper, and NetEase board parsers reject malformed success envelopes.
- [ ] All three daily boards are anonymous and fetched exactly once per run.
- [ ] User requests never call a hot-board endpoint.
- [ ] Formal results are constructible only from accepted full text and verified heat evidence.
- [ ] Summary, title-only, video, image, live, paywall, external placeholder, and page-chrome records are rejected.
- [ ] Five cached matches skip search.
- [ ] Fewer than five cached matches trigger bounded search.
- [ ] Search scans no more than sixty unique candidates and returns no more than twenty results.
- [ ] Search rank and response count are never heat evidence.
- [ ] Dynamic floors use positive official-board samples and configured absolute fallbacks.
- [ ] Official and search-qualified results are deduplicated and uniformly heat-ranked.
- [ ] Same-day search and user-result caches prevent duplicate external calls.
- [ ] Platform failures remain isolated and sanitized.
- [ ] Active snapshots are atomically published and stale usage is bounded to 48 hours.
- [ ] Real smoke artifacts contain no credentials and are not committed.
- [ ] `uv run pytest -q`, compileall, and `git diff --check` pass.
