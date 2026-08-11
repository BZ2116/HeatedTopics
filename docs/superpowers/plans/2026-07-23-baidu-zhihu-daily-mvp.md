# Baidu Hot Search and Zhihu Daily MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add anonymous Baidu Hot Search and Zhihu Daily providers that produce ranked hot/recommended records with verified full text and bounded keyword discovery.

**Architecture:** Extend the cached-news orchestration with optional provider hooks for context-aware search, official rank-only evidence, and provider-specific ordering. Implement Baidu as a hot-event provider whose heat comes from the official board and whose body comes from a separately attributed supporting article; implement Zhihu Daily from its latest, detail, and seven-day archive APIs.

**Tech Stack:** Python 3.14, `httpx`, `html.parser`, `gne`, frozen dataclass contracts, filesystem cache, `pytest`, `uv`.

## Global Constraints

- Work only in `E:\.code\My\heatedTopics\heatedTopics\.worktrees\baidu-zhihu-daily-mvp` on branch `feature/baidu-zhihu-daily-mvp`.
- Base commit is `2aeca86`; approved design commit is `9cb6086`.
- Do not modify or copy uncommitted files from another worktree.
- Do not send persistent Cookies, authorization headers, API keys, or login state.
- Do not use Playwright, CAPTCHA bypass, an LLM, or embedding-based matching.
- Every formal result requires `content_status == "full_text"`, accepted content validation, and truthful heat evidence.
- Native structured/container text requires at least 80 effective characters; GNE fallback requires at least 200.
- Every accepted body also requires at least 2 real paragraphs or 3 complete sentences.
- Cached matches of 5 or more skip search.
- Search uses pages of 15, examines at most 60 unique candidates, and returns at most 20 results per platform.
- User requests never refresh an official hot board.
- A normal search result without current official Baidu event evidence or Zhihu Daily recommendation evidence is rejected.
- Existing Toutiao, Juejin, Sina News, The Paper, and NetEase behavior must remain unchanged.

---

## File Structure

### New files

- `src/heated_topics_v3/providers/baidu_hot.py` — Baidu board parsing, search-card parsing, event/article linkage, body extraction, contextual search, and heat evidence.
- `src/heated_topics_v3/providers/zhihu_daily.py` — latest and archive parsing, story detail extraction, official rank evidence, and date/rank ordering.
- `tests/providers/test_baidu_hot.py` — Baidu unit and contract tests.
- `tests/providers/test_zhihu_daily.py` — Zhihu Daily unit and contract tests.
- `tests/fixtures/baidu_hot_board.html` — deterministic `s-data` board envelope.
- `tests/fixtures/baidu_search.html` — deterministic Baidu result cards.
- `tests/fixtures/baidu_public_article.html` — accepted supporting article.
- `tests/fixtures/zhihu_daily_latest.json` — deterministic latest response.
- `tests/fixtures/zhihu_daily_detail.json` — deterministic detail response.
- `tests/fixtures/zhihu_daily_before_20260722.json` — first archive response.
- `tests/fixtures/zhihu_daily_before_20260721.json` — second archive response.
- `docs/specs/baidu-zhihu-daily-mvp-implementation-report.md` — live verification record.

### Modified files

- `src/heated_topics_v3/providers/common.py` — optional capability protocols.
- `src/heated_topics_v3/discovery.py` — contextual search, provider evidence hook, and provider ranking hook.
- `src/heated_topics_v3/collection.py` — official rank-only board evidence hook and provider ordering.
- `src/heated_topics_v3/providers/__init__.py` — export both providers.
- `src/heated_topics_v3/recommendation.py` — add display order and preserve detail source URL.
- `src/heated_topics_v3/cli.py` — register both providers in cached-news commands.
- `tests/test_discovery.py` — optional hook behavior and regression coverage.
- `tests/test_news_collection.py` — rank-only board qualification.
- `tests/test_news_recommendation.py` — five-platform ordering and body source attribution.
- `tests/test_news_cli.py` — five-provider registration and anonymous client coverage.
- `tests/providers/test_provider_contracts.py` — static provider contract coverage.
- `tools/validate_news_smoke.py` — accept official rank-only evidence without weakening public-engagement checks.
- `tests/test_news_smoke_validator.py` — validator regression.
- `README.md` — document the two new sources and their evidence/body semantics.

---

### Task 1: Add Optional Provider Capabilities

**Files:**
- Modify: `src/heated_topics_v3/providers/common.py`
- Modify: `src/heated_topics_v3/discovery.py`
- Modify: `src/heated_topics_v3/collection.py`
- Test: `tests/test_discovery.py`
- Test: `tests/test_news_collection.py`

**Interfaces:**
- Consumes: existing `NewsProvider`, `QualifiedArticle`, `HeatEvidence`, and `rank_platform_articles`.
- Produces: optional `search_with_context`, `build_board_evidence`, `build_search_evidence`, and `rank_articles` runtime hooks.

- [ ] **Step 1: Write failing discovery hook tests**

Add a `HookProvider` test double to `tests/test_discovery.py` that records contextual search input, returns official search evidence without public metrics, and reverses deterministic order:

```python
class HookProvider(FakeProvider):
    def __init__(self, pages=()):
        super().__init__(
            "rank_only",
            weights={},
            absolute_floors={},
            pages=pages,
        )
        self.context_calls = []

    def search_with_context(
        self, keyword, page, page_size, collected_at, official_articles
    ):
        self.context_calls.append(
            (keyword, page, page_size, tuple(
                article.hot_item.item_id for article in official_articles
            ))
        )
        return super().search(keyword, page, page_size, collected_at)

    def build_search_evidence(self, item, floors):
        return HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=item.rank,
            native_hot_value=None,
            metrics={},
            threshold_metrics={},
            qualified_by=("official_hot_board",),
        )

    def rank_articles(self, articles):
        return tuple(reversed(tuple(articles)))
```

Add tests proving:

```python
def test_optional_context_evidence_and_rank_hooks_are_used(repository):
    seeded = _seed_eligible(repository, "rank_only", count=1)
    search_item = _make_hot_item(
        platform="rank_only",
        item_id="rank_only_archive_1",
        rank=2,
        title=f"{KEYWORD} 归档推荐",
        summary=KEYWORD,
        metrics={},
    )
    provider = HookProvider(pages=((search_item,),))

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )

    assert provider.context_calls[0][3] == (seeded[0].hot_item.item_id,)
    assert any(
        article.hot_item.item_id == "rank_only_archive_1" for article in result
    )
    assert all(
        article.heat_evidence.source_kind == "official_hot_board"
        for article in result
    )
```

- [ ] **Step 2: Write failing collection rank-only evidence test**

Add a provider double to `tests/test_news_collection.py` with empty metrics and:

```python
def build_board_evidence(self, item, floors):
    return HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=item.rank,
        native_hot_value=None,
        metrics={},
        threshold_metrics={},
        qualified_by=("official_hot_board",),
    )
```

Assert one full-text rank-only item is written to `eligible/rank_only.json`
instead of `rejected/rank_only.json`.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
uv run pytest tests/test_discovery.py tests/test_news_collection.py -q
```

Expected: failures show contextual search is not called and the rank-only item
is rejected for missing metrics.

- [ ] **Step 4: Add optional capability protocols**

In `providers/common.py`, add protocols with the approved signatures:

```python
class ContextualSearchProvider(Protocol):
    def search_with_context(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
        official_articles: Sequence[QualifiedArticle],
    ) -> ProviderCapture: ...


class BoardEvidenceProvider(Protocol):
    def build_board_evidence(
        self, item: HotItem, floors: Mapping[str, float]
    ) -> HeatEvidence | None: ...


class SearchEvidenceProvider(Protocol):
    def build_search_evidence(
        self, item: HotItem, floors: Mapping[str, float]
    ) -> HeatEvidence | None: ...


class ArticleRankingProvider(Protocol):
    def rank_articles(
        self, articles: Sequence[QualifiedArticle]
    ) -> tuple[QualifiedArticle, ...]: ...
```

Import `HeatEvidence` and `QualifiedArticle` from contracts.

- [ ] **Step 5: Route discovery through the optional hooks**

Add private helpers to `discovery.py`:

```python
def _provider_search(provider, keyword, page, page_size, collected_at, official):
    contextual = getattr(provider, "search_with_context", None)
    if callable(contextual):
        return contextual(
            keyword, page, page_size, collected_at, tuple(official)
        )
    return provider.search(keyword, page, page_size, collected_at)


def _provider_search_evidence(provider, item, floors):
    builder = getattr(provider, "build_search_evidence", None)
    if callable(builder):
        return builder(item, floors)
    metrics = dict(item.heat.metrics)
    qualified_by = qualifies_public_metrics(metrics, floors)
    if not metrics or not qualified_by:
        return None
    return HeatEvidence(
        source_kind="public_engagement",
        platform_rank=None,
        native_hot_value=None,
        metrics=metrics,
        threshold_metrics=dict(floors),
        qualified_by=tuple(qualified_by),
    )


def _rank_with_provider(provider, articles):
    ranker = getattr(provider, "rank_articles", None)
    if callable(ranker):
        return tuple(ranker(tuple(articles)))
    return rank_platform_articles(tuple(articles), provider.weights)
```

Use `_provider_search` inside `_run_search_discovery`, passing
`seeded_matched`. Replace the unconditional public-metric evidence construction
with `_provider_search_evidence`. Use `_rank_with_provider` in every cached,
snapshot, merge, and final ranking path.

- [ ] **Step 6: Route daily collection through board evidence**

In `_collect_news_platform`, call `build_board_evidence` when present. If it
returns `None`, reject the item. If the hook is absent, retain the existing
metric guard and `_build_official_evidence`. Apply `rank_articles` before
persisting eligible records when the provider supplies it.

- [ ] **Step 7: Run focused and full tests**

Run:

```powershell
uv run pytest tests/test_discovery.py tests/test_news_collection.py -q
uv run pytest -q
```

Expected: focused tests pass and the full suite remains at least 277 passing.

- [ ] **Step 8: Commit**

```powershell
git add src/heated_topics_v3/providers/common.py src/heated_topics_v3/discovery.py src/heated_topics_v3/collection.py tests/test_discovery.py tests/test_news_collection.py
git commit -m "feat: support contextual official discovery"
```

---

### Task 2: Implement Baidu Official Board Parsing

**Files:**
- Create: `src/heated_topics_v3/providers/baidu_hot.py`
- Create: `tests/providers/test_baidu_hot.py`
- Create: `tests/fixtures/baidu_hot_board.html`
- Modify: `tests/providers/test_provider_contracts.py`

**Interfaces:**
- Produces: `BaiduHotProvider.collect_hot_list`, `parse_hot_list`,
  `platform="baidu_hot"`, `weights={"hot_score": 1.0}`, and
  `absolute_floors={"hot_score": 1.0}`.

- [ ] **Step 1: Add the board fixture**

Create `tests/fixtures/baidu_hot_board.html` containing:

```html
<!doctype html>
<html><body>
<!--s-data:{"data":{"cards":[{"content":[
  {"index":1,"word":"人工智能手机发布","desc":"新产品和行业变化引发讨论","hotScore":"987654","query":"人工智能手机发布","rawUrl":"https://example.test/article/ai-phone","img":"https://example.test/cover.jpg"},
  {"index":2,"title":"暑期旅行避坑","desc":"消费者关注出游体验","hotTag":"456789","query":"暑期旅行避坑","url":"https://www.baidu.com/s?wd=travel"}
]}]}}-->
</body></html>
```

- [ ] **Step 2: Write failing board contract tests**

In `tests/providers/test_baidu_hot.py`, test:

```python
def test_parse_hot_list_preserves_rank_hot_score_and_event_provenance():
    raw = FIXTURES.joinpath("baidu_hot_board.html").read_text("utf-8")
    items = BaiduHotProvider.parse_hot_list(raw, NOW)

    assert [item.rank for item in items] == [1, 2]
    assert [item.heat.value for item in items] == [987654, 456789]
    assert items[0].heat.metrics == {"hot_score": 987654}
    assert items[0].title == "人工智能手机发布"
    assert items[0].raw_payload["rawUrl"].endswith("/ai-phone")
    assert items[0].item_id.startswith("baidu_hot_")
    assert items[0].item_id != items[1].item_id
```

Also parameterize malformed cases: missing marker, invalid JSON, empty content,
and rows without title/query. Test `collect_hot_list` calls
`raise_for_status()` on HTTP 503.

- [ ] **Step 3: Run the provider test and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_baidu_hot.py -q
```

Expected: import failure for the missing provider module.

- [ ] **Step 4: Implement strict board parsing**

Implement:

```python
BAIDU_HOT_URL = "https://top.baidu.com/board?tab=realtime"
BAIDU_WEIGHTS = {"hot_score": 1.0}
BAIDU_ABSOLUTE_FLOORS = {"hot_score": 1.0}
_S_DATA = re.compile(r"<!--s-data:(.*?)-->", re.DOTALL)


def _stable_event_id(query: str) -> str:
    normalized = " ".join(normalize("NFKC", query).casefold().split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"baidu_hot_{digest}"
```

`parse_hot_list` must accept both `data.cards[0].content` and
`cards[0].content`, unwrap one nested `content` list, keep valid rows, use the
enumerated official position as rank, and fail when no valid items remain.

- [ ] **Step 5: Add static contract assertions**

Extend `test_provider_contracts.py`:

```python
def test_baidu_hot_provider_attributes_match_spec():
    provider = _instantiate(BaiduHotProvider)
    assert provider.platform == "baidu_hot"
    assert provider.weights == {"hot_score": 1.0}
    assert provider.absolute_floors == {"hot_score": 1.0}
```

- [ ] **Step 6: Run tests and commit**

```powershell
uv run pytest tests/providers/test_baidu_hot.py tests/providers/test_provider_contracts.py -q
git add src/heated_topics_v3/providers/baidu_hot.py tests/providers/test_baidu_hot.py tests/providers/test_provider_contracts.py tests/fixtures/baidu_hot_board.html
git commit -m "feat: parse baidu official hot board"
```

---

### Task 3: Add Baidu Supporting Bodies and Contextual Search

**Files:**
- Modify: `src/heated_topics_v3/providers/baidu_hot.py`
- Modify: `tests/providers/test_baidu_hot.py`
- Create: `tests/fixtures/baidu_search.html`
- Create: `tests/fixtures/baidu_public_article.html`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces: `fetch_detail`, `search_with_context`, `build_search_evidence`,
  deterministic event/article relevance, resolved source attribution.

- [ ] **Step 1: Add search and article fixtures**

Create a Baidu search fixture with two cards:

```html
<div class="result c-container">
  <h3><a href="https://www.baidu.com/link?url=valid">人工智能手机正式发布</a></h3>
  <span class="c-abstract">人工智能手机发布后，用户关注实际功能。</span>
</div>
<div class="result c-container">
  <h3><a href="https://www.baidu.com/link?url=unrelated">无关体育比赛</a></h3>
  <span class="c-abstract">比赛结果和球队积分。</span>
</div>
```

Create an article fixture with four paragraphs inside `<article>` and more than
200 effective characters.

- [ ] **Step 2: Write failing detail and contextual search tests**

Cover:

```python
def test_fetch_detail_uses_resolved_supporting_article_and_preserves_source():
    provider = BaiduHotProvider(client_with_search_redirect_and_article())
    item = board_item("人工智能手机发布", hot_score=987654)

    detail = provider.fetch_detail(item, NOW)

    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"
    assert detail.source_url == "https://news.example.test/ai-phone"
    assert "人工智能手机" in detail.content
```

```python
def test_context_search_inherits_parent_event_evidence_without_board_refresh():
    parent = qualified_baidu_event()
    provider = BaiduHotProvider(client_with_search_redirect_and_article())

    capture = provider.search_with_context(
        "人工智能", 1, 15, NOW, (parent,)
    )

    assert len(capture.items) == 1
    item = capture.items[0]
    assert item.rank == parent.hot_item.rank
    assert item.heat.metrics == parent.hot_item.heat.metrics
    assert item.raw_payload["parent_event_id"] == parent.hot_item.item_id
    assert item.item_id != parent.hot_item.item_id
```

Add negative tests for CAPTCHA HTML, search/topic URLs, unrelated result,
redirect loop, short body, summary-equivalent body, and no official context.

- [ ] **Step 3: Run Baidu tests and verify RED**

```powershell
uv run pytest tests/providers/test_baidu_hot.py tests/test_discovery.py -q
```

Expected: missing `fetch_detail`, `search_with_context`, and evidence behavior.

- [ ] **Step 4: Implement result-card parsing and URL resolution**

Add a bounded HTML parser that captures result-card title, href, and abstract.
Only accept HTTP(S) links. Resolve Baidu redirects through the injected
`httpx.Client`, reject final hosts/paths that are Baidu search, login, video,
image, or aggregation surfaces, and never persist response headers.

- [ ] **Step 5: Implement deterministic relevance**

Normalize strings with NFKC and casefold. Require the normalized user keyword
in candidate title, abstract, or body. Event relevance is true when:

- an event title of four or fewer normalized characters is an exact substring;
  or
- at least two adjacent CJK bigrams overlap and overlap is at least 25% of the
  smaller bigram set; or
- one normalized alphanumeric token of length at least three is shared.

Tests must prove a related phone article passes and the sports article fails.

- [ ] **Step 6: Implement body extraction**

Extraction order:

```python
def _extract_public_article(html: str) -> tuple[str, str]:
    structured = _json_ld_article_body(html)
    if structured:
        return structured, "json_ld"
    native = article_text(html)
    if native:
        return native, "article"
    extracted = GeneralNewsExtractor().extract(html)
    return str(extracted.get("content") or ""), "gne"
```

Validate with `validate_full_text`. `fetch_detail` first tries an article-like
`rawUrl`; otherwise it searches the exact event title and inspects candidates
until one accepted body is found.

- [ ] **Step 7: Implement contextual search and evidence**

Map generic search page N deterministically across matched parent events:

```python
parent_index = (page - 1) % len(official_articles)
result_page = ((page - 1) // len(official_articles)) + 1
```

Query the selected parent event title, slice to `page_size`, attach
`parent_event_id`, `parent_event_title`, `parent_rank`, and `parent_hot_score`
to each result, and build item IDs from parent digest plus resolved URL digest.

`build_search_evidence` returns:

```python
HeatEvidence(
    source_kind="official_hot_board",
    platform_rank=parent_rank,
    native_hot_value=parent_hot_score,
    metrics={"hot_score": parent_hot_score},
    threshold_metrics=dict(floors),
    qualified_by=("official_hot_board",),
)
```

- [ ] **Step 8: Run focused and full tests**

```powershell
uv run pytest tests/providers/test_baidu_hot.py tests/test_discovery.py -q
uv run pytest -q
```

- [ ] **Step 9: Commit**

```powershell
git add src/heated_topics_v3/providers/baidu_hot.py tests/providers/test_baidu_hot.py tests/test_discovery.py tests/fixtures/baidu_search.html tests/fixtures/baidu_public_article.html
git commit -m "feat: resolve baidu hot event articles"
```

---

### Task 4: Implement Zhihu Daily Latest and Detail

**Files:**
- Create: `src/heated_topics_v3/providers/zhihu_daily.py`
- Create: `tests/providers/test_zhihu_daily.py`
- Create: `tests/fixtures/zhihu_daily_latest.json`
- Create: `tests/fixtures/zhihu_daily_detail.json`
- Modify: `tests/providers/test_provider_contracts.py`

**Interfaces:**
- Produces: latest list parsing, public detail extraction, and rank-only board
  evidence.

- [ ] **Step 1: Add latest and detail fixtures**

Latest fixture:

```json
{
  "date": "20260723",
  "stories": [
    {
      "id": 1001,
      "title": "人工智能工具如何改变内容创作",
      "hint": "作者 · 5 分钟阅读",
      "type": 0,
      "url": "https://daily.zhihu.com/story/1001",
      "images": ["https://example.test/1001.jpg"]
    },
    {
      "id": 1002,
      "title": "视频故事不在正文范围",
      "hint": "视频",
      "type": 1,
      "url": "https://daily.zhihu.com/story/1002"
    }
  ]
}
```

Detail fixture contains `id`, `title`, `share_url`, and a `body` with four
paragraphs and at least 80 effective characters.

- [ ] **Step 2: Write failing latest/detail tests**

Assert:

```python
def test_latest_keeps_type_zero_and_uses_official_rank_only():
    items = ZhihuDailyProvider.parse_latest(
        FIXTURES.joinpath("zhihu_daily_latest.json").read_text("utf-8"), NOW
    )
    assert len(items) == 1
    assert items[0].item_id == "zhihu_daily_1001"
    assert items[0].rank == 1
    assert items[0].heat.value is None
    assert items[0].heat.metrics == {}
    assert items[0].raw_payload["recommendation_date"] == "20260723"
```

```python
def test_detail_api_body_is_clean_full_text():
    provider = ZhihuDailyProvider(client_with_latest_and_detail())
    detail = provider.fetch_detail(latest_item(), NOW)
    assert detail.content_status == "full_text"
    assert detail.source_url == "https://daily.zhihu.com/story/1001"
    assert "<p>" not in detail.content
    assert detail.content.count("\n") >= 1
```

Test malformed JSON, missing/empty `stories`, all unsupported story types,
missing body, title-only body, and HTTP 503.

- [ ] **Step 3: Run tests and verify RED**

```powershell
uv run pytest tests/providers/test_zhihu_daily.py -q
```

- [ ] **Step 4: Implement latest and detail**

Use:

```python
ZHIHU_DAILY_LATEST_URL = "https://daily.zhihu.com/api/4/news/latest"
ZHIHU_DAILY_DETAIL_URL = "https://daily.zhihu.com/api/4/news/{story_id}"
```

Set:

```python
platform = "zhihu_daily"
weights = {}
absolute_floors = {}
```

Parse only `type == 0`. Preserve response `date`. Use a dedicated HTML parser
that flushes paragraphs at `p`, `div`, `section`, `blockquote`, `br`, and
heading boundaries while ignoring `script`, `style`, `nav`, and `footer`.

- [ ] **Step 5: Implement rank-only board evidence**

```python
def build_board_evidence(self, item, floors):
    if item.rank is None or item.rank <= 0:
        return None
    return HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=item.rank,
        native_hot_value=None,
        metrics={},
        threshold_metrics={},
        qualified_by=("official_hot_board",),
    )
```

- [ ] **Step 6: Add static contract assertions and commit**

```powershell
uv run pytest tests/providers/test_zhihu_daily.py tests/providers/test_provider_contracts.py -q
git add src/heated_topics_v3/providers/zhihu_daily.py tests/providers/test_zhihu_daily.py tests/providers/test_provider_contracts.py tests/fixtures/zhihu_daily_latest.json tests/fixtures/zhihu_daily_detail.json
git commit -m "feat: collect zhihu daily full stories"
```

---

### Task 5: Add Seven-Day Zhihu Daily Archive Search

**Files:**
- Modify: `src/heated_topics_v3/providers/zhihu_daily.py`
- Modify: `tests/providers/test_zhihu_daily.py`
- Create: `tests/fixtures/zhihu_daily_before_20260722.json`
- Create: `tests/fixtures/zhihu_daily_before_20260721.json`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces: bounded archive cache, paginated local search, official archive
  evidence, and newest-date-first ordering.

- [ ] **Step 1: Add archive fixtures**

Each fixture contains a `date` and type-0 stories. Include one duplicate story
ID across both days, one keyword match, one non-match, and ranks that differ
from date order.

- [ ] **Step 2: Write failing archive tests**

Test:

```python
def test_archive_search_scans_seven_days_once_and_pages_cached_matches():
    provider = ZhihuDailyProvider(client_with_seven_archive_days())
    first = provider.search("人工智能", 1, 15, NOW)
    second = provider.search("人工智能", 2, 15, NOW)

    assert all("人工智能" in item.title or "人工智能" in item.summary for item in first.items + second.items)
    assert len({item.item_id for item in first.items + second.items}) == len(first.items + second.items)
    assert archive_request_count(provider.client) == 7
```

Test a hard slice of at most 60 unique items and a page size of 15. Test HTTP or
schema failure is not converted to a successful empty archive.

- [ ] **Step 3: Write failing evidence and order tests**

Construct archive articles with dates `20260722` and `20260721`, ranks 3 and 1.
Assert newest date sorts first even when its within-day rank is larger.

- [ ] **Step 4: Run tests and verify RED**

```powershell
uv run pytest tests/providers/test_zhihu_daily.py tests/test_discovery.py -q
```

- [ ] **Step 5: Implement a seven-day in-memory archive cache**

On the first `search` call per `(keyword, collected_at date)`, request:

```text
/api/4/news/before/<date>
```

for seven preceding dates, parse official date/rank, deduplicate by story ID,
prefilter title and hint with existing NFKC substring semantics, and retain at
most 60 records. Later pages slice the cached tuple without new HTTP calls.

- [ ] **Step 6: Implement archive evidence**

`build_search_evidence` requires:

- positive `item.rank`;
- an eight-digit `recommendation_date`;
- `raw_payload["official_recommendation"] is True`.

It returns rank-only `official_hot_board` evidence with empty metrics.

- [ ] **Step 7: Implement provider ordering**

`rank_articles` uses explicit stable sorts:

```python
ordered = sorted(
    (replace(article, platform_heat_score=0.0) for article in articles),
    key=lambda article: article.hot_item.item_id,
)
ordered.sort(
    key=lambda article: article.hot_item.publication_time or "",
    reverse=True,
)
ordered.sort(
    key=lambda article: article.heat_evidence.platform_rank or 10**9,
)
ordered.sort(
    key=lambda article: str(
        article.hot_item.raw_payload.get("recommendation_date") or ""
    ),
    reverse=True,
)
return tuple(ordered)
```

This gives descending recommendation date, ascending within-day rank,
descending publication time, and stable story ID. Do not rely on Python hash
values.

- [ ] **Step 8: Run focused and full tests**

```powershell
uv run pytest tests/providers/test_zhihu_daily.py tests/test_discovery.py -q
uv run pytest -q
```

- [ ] **Step 9: Commit**

```powershell
git add src/heated_topics_v3/providers/zhihu_daily.py tests/providers/test_zhihu_daily.py tests/test_discovery.py tests/fixtures/zhihu_daily_before_20260722.json tests/fixtures/zhihu_daily_before_20260721.json
git commit -m "feat: search zhihu daily archives"
```

---

### Task 6: Register Both Providers in the Cached-News Workflow

**Files:**
- Modify: `src/heated_topics_v3/providers/common.py`
- Modify: `src/heated_topics_v3/providers/__init__.py`
- Modify: `src/heated_topics_v3/recommendation.py`
- Modify: `src/heated_topics_v3/cli.py`
- Modify: `tests/test_news_collection.py`
- Modify: `tests/test_news_recommendation.py`
- Modify: `tests/test_news_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `BaiduHotProvider`, `ZhihuDailyProvider`.
- Produces: five-platform `collect-news` and `generate-news`.

- [ ] **Step 1: Write failing registration and ordering tests**

Update expected platforms to:

```python
(
    "sina_news",
    "thepaper",
    "netease_news",
    "baidu_hot",
    "zhihu_daily",
)
```

Test `_news_providers` returns all five provider classes. Test collection
isolates a failing Baidu provider while saving Zhihu Daily. Test generation
metadata includes both new platforms.

- [ ] **Step 2: Write failing supporting source attribution test**

Create a `QualifiedArticle` whose:

```text
hot_item.url = https://www.baidu.com/s?wd=event
detail.source_url = https://news.example.test/article
```

Assert the generated `RecommendationItem.source_url` is the supporting article
URL.

- [ ] **Step 3: Run integration tests and verify RED**

```powershell
uv run pytest tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py -q
```

- [ ] **Step 4: Register the providers**

Extend `NEWS_PLATFORMS`, `NEWS_DISPLAY_ORDER`, provider exports, and
`cli._news_providers`. Do not change the existing `collect-news` or
`generate-news` command names.

- [ ] **Step 5: Preserve actual body source attribution**

Change `_article_to_recommendation` to:

```python
source_url=article.detail.source_url or article.hot_item.url
```

Keep the Baidu event URL and parent event fields in evidence/raw payload.

- [ ] **Step 6: Update documentation**

Document:

- Baidu heat is event-level and its body source is separate.
- Zhihu Daily heat evidence is official date/rank, not engagement.
- Both providers are anonymous and cookie-free.
- Zhihu search means a bounded seven-day archive scan.

- [ ] **Step 7: Run full tests and commit**

```powershell
uv run pytest -q
git add src/heated_topics_v3/providers/common.py src/heated_topics_v3/providers/__init__.py src/heated_topics_v3/recommendation.py src/heated_topics_v3/cli.py tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py README.md
git commit -m "feat: register baidu and zhihu daily providers"
```

---

### Task 7: Harden Smoke Validation and Run Live Verification

**Files:**
- Modify: `tools/validate_news_smoke.py`
- Modify: `tests/test_news_smoke_validator.py`
- Create: `docs/specs/baidu-zhihu-daily-mvp-implementation-report.md`

**Interfaces:**
- Produces: truthful validation for official rank-only evidence and a reproducible
  live verification record.

- [ ] **Step 1: Write failing validator tests**

Add a clean `zhihu_daily` result containing:

```json
{
  "content_status": "full_text",
  "detail": "accepted body",
  "evidence": {
    "source_kind": "official_hot_board",
    "platform_rank": 1,
    "native_hot_value": null,
    "metrics": {},
    "qualified_by": ["official_hot_board"],
    "platform_heat_score": 0.0
  }
}
```

Assert it passes. Add a `public_engagement` result with empty metrics and assert
it still fails.

- [ ] **Step 2: Run validator tests and verify RED**

```powershell
uv run pytest tests/test_news_smoke_validator.py -q
```

Expected: official rank-only evidence is incorrectly reported as missing
metrics.

- [ ] **Step 3: Update the validator**

Require:

```python
qualified_by is nonempty
```

For `source_kind == "official_hot_board"`, accept either positive
`platform_rank`, positive `native_hot_value`, or positive metrics. For
`source_kind == "public_engagement"`, continue requiring a named positive
metric. Do not relax content, limit, ordering, overlap, JSON, or credential
checks.

- [ ] **Step 4: Run automated verification**

```powershell
uv run pytest tests/providers/test_baidu_hot.py tests/providers/test_zhihu_daily.py tests/test_discovery.py tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py tests/test_news_smoke_validator.py -q
uv run pytest -q
uv run python -m compileall -q src tests
git diff --check
```

Expected: every command exits 0 with no warnings from project code.

- [ ] **Step 5: Run anonymous live smoke collection**

Create a temporary directory with PowerShell and run:

```powershell
$smokeRoot = Join-Path $env:TEMP ('heatedtopics-baidu-zhihu-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
uv run heated-topics collect-news --data-root $smokeRoot
uv run python tools/validate_news_smoke.py $smokeRoot
```

Inspect:

- raw and normalized item counts;
- Baidu positive `hot_score`;
- Baidu supporting article success/rejection counts;
- Zhihu Daily latest and detail success/rejection counts;
- persisted files for credential-shaped strings.

- [ ] **Step 6: Run one search-triggering profile per provider**

Use temporary profile JSON files with keywords selected from the current Baidu
and Zhihu Daily snapshots. Run `generate-news` twice for each profile and
confirm the second run returns `existing` without new search requests.

- [ ] **Step 7: Record the implementation report**

Write exact commands, commit SHAs, test counts, live endpoint counts,
qualification/rejection counts, known limitations, and credential scan result
to `docs/specs/baidu-zhihu-daily-mvp-implementation-report.md`. Do not copy full
article bodies into the report or repository.

- [ ] **Step 8: Commit**

```powershell
git add tools/validate_news_smoke.py tests/test_news_smoke_validator.py docs/specs/baidu-zhihu-daily-mvp-implementation-report.md
git commit -m "docs: verify baidu and zhihu daily mvp"
```

---

## Final Review Checklist

- [ ] Every new production function was preceded by a failing test.
- [ ] Each RED failure was caused by missing behavior rather than a broken test.
- [ ] Baidu board requests occur only during daily collection.
- [ ] Baidu user search receives cached qualified parent events as context.
- [ ] Baidu article URLs and event heat provenance remain separate.
- [ ] Zhihu latest and archive records never invent engagement metrics.
- [ ] Zhihu archive scan is bounded to seven days and 60 unique candidates.
- [ ] Search is skipped at 5 cached matches and capped at 20 results.
- [ ] Existing five older providers retain their prior tests and behavior.
- [ ] Full suite, compileall, diff check, validator, and live smoke all pass.
- [ ] Worktree contains no committed raw smoke data, credentials, or large
  copyrighted bodies.
