# Hot Topic Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and manually verify the complete five-platform hot-list collection, full-detail capture, keyword recommendation, Toutiao search, Qianfan fallback, and file-output workflow.

**Architecture:** Keep platform-specific HTTP and parsing logic in provider modules, normalize all sources into immutable contracts, and coordinate them through separate daily-collection and per-user-generation services. Store raw captures, normalized snapshots, details, and user results behind one filesystem repository so the CLI and downstream Python API share identical behavior.

**Tech Stack:** Python 3.10+, dataclasses, `httpx`, `playwright`, `python-dotenv`, `pytest`, JSON/Markdown/TXT filesystem artifacts.

## Global Constraints

- The first iteration is manually triggered; do not add a persistent scheduler or frontend behavior.
- Platform display order is exactly `toutiao`, `baidu`, `juejin`, `weibo`, `zhihu`.
- Toutiao and Baidu are primary sources; Juejin, Weibo, and Zhihu are auxiliary sources.
- Match personalized records using only the saved `primary_keyword`; do not call an LLM for relevance.
- Preserve duplicate events across different platforms and never compute a cross-platform heat score.
- Level 1 requires official hot-list evidence; Level 2 requires explicit numeric heat or engagement; Level 3 has no official or numeric heat evidence.
- Search and fallback results must be from the most recent 24 hours.
- The business day begins at 08:00 in `Asia/Shanghai`.
- Permanently retain test-phase raw captures, normalized snapshots, detail files, profiles, and user outputs.
- Store secrets only in environment variables. Never serialize Cookies or API keys.
- TXT output contains only title, platform, heat level, publication time, collection time, and detail content.
- Never invent missing text. Fall back from full text to source summary to title.
- Use test-driven development and commit after every task.

---

## Planned File Structure

```text
src/heated_topics_v3/
├── __init__.py                 # public Python API exports
├── cli.py                      # manual collect and generate commands
├── clock.py                    # Asia/Shanghai business-day rules
├── contracts.py                # immutable normalized data contracts
├── profiles.py                 # profile JSON load/save and Qianfan query construction
├── matching.py                 # primary-keyword matching and heat classification
├── storage.py                  # filesystem layout, raw/JSON/TXT writes, atomic results
├── collection.py               # five-platform daily collection orchestration
├── recommendation.py           # once-per-user generation workflow
├── reporting.py                # Markdown, JSON, and minimal TXT rendering
└── providers/
    ├── __init__.py
    ├── common.py               # shared HTTP result and text helpers
    ├── toutiao.py              # board, keyword search, and article detail
    ├── baidu.py                # board HTML and embedded explanation
    ├── juejin.py               # rank and article-detail APIs
    ├── weibo.py                # Cookie hot search and topic detail
    ├── zhihu.py                # Cookie hot list and answer detail
    └── qianfan.py              # one-call web-search fallback

tests/
├── fixtures/                   # sanitized provider responses
├── providers/                  # parser and fetch fallback tests
├── test_clock.py
├── test_contracts.py
├── test_profiles.py
├── test_matching.py
├── test_storage.py
├── test_collection.py
├── test_recommendation.py
├── test_reporting.py
└── test_cli.py
```

### Task 1: Replace Legacy Contracts With Workflow Contracts

**Files:**
- Modify: `src/heated_topics_v3/contracts.py`
- Modify: `tests/test_contracts.py`

**Interfaces:**
- Produces: `UserProfile`, `HeatMetrics`, `HotItem`, `ItemDetail`, `PlatformCollectionStatus`, `DailySnapshot`, `RecommendationItem`, `RecommendationBundle`, and string-literal status aliases used by all later tasks.
- Consumes: no new internal interfaces.

- [ ] **Step 1: Write failing contract tests**

Add tests that construct a profile with `primary_track`, `secondary_track`, `persona`, and `primary_keyword`; construct a Level 1 recommendation with `fact_status="unverified"`; and assert that `ItemDetail.content_status` accepts `full_text`, `summary`, and `title_only`.

```python
def test_user_profile_stores_primary_keyword():
    profile = UserProfile(
        user_id="u1",
        primary_track="人工智能",
        secondary_track="AI应用",
        persona="职场工具测评",
        primary_keyword="AI工具",
        updated_at="2026-07-13T08:00:00+08:00",
    )
    assert profile.primary_keyword == "AI工具"


def test_recommendation_keeps_heat_and_fact_status():
    item = RecommendationItem(
        hot_item_id="baidu_1",
        platform="baidu",
        title="测试热点",
        heat_level=1,
        fact_status="unverified",
        publication_time=None,
        collected_at="2026-07-13T08:00:00+08:00",
        detail="热点解释",
        content_status="summary",
        is_personalized=True,
        evidence={"rank": 1, "hot_index": 100},
    )
    assert item.heat_level == 1
    assert item.fact_status == "unverified"
```

- [ ] **Step 2: Run tests and confirm the legacy contract fails**

Run: `uv run pytest tests/test_contracts.py -q`

Expected: FAIL because the current `UserProfile` and recommendation contracts do not expose the required fields.

- [ ] **Step 3: Implement the complete normalized contracts**

Use frozen dataclasses. Define exact literals:

```python
HeatLevel = Literal[1, 2, 3]
FactStatus = Literal["verified", "unverified", "disputed", "debunked"]
ContentStatus = Literal["full_text", "summary", "title_only"]
GenerationStatus = Literal["existing", "generated", "no_result", "not_ready", "failed"]
```

`HotItem` must include `item_id`, `platform`, `title`, `url`, `rank`, `heat`, `summary`, `publication_time`, `collected_at`, and `raw_payload`. `ItemDetail` must include `item_id`, `content`, `content_status`, `publication_time`, `collected_at`, `source_url`, and `fetch_status`. `DailySnapshot` must group immutable item tuples by platform. `RecommendationBundle` must include `status`, `user_id`, `business_date`, `generated_at`, formal recommendations, potential topics, general fallback records, and query metadata.

- [ ] **Step 4: Run the contract tests**

Run: `uv run pytest tests/test_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/contracts.py tests/test_contracts.py
git commit -m "feat: define recommendation workflow contracts"
```

### Task 2: Add Business-Day and Profile Services

**Files:**
- Create: `src/heated_topics_v3/clock.py`
- Create: `src/heated_topics_v3/profiles.py`
- Replace: `src/heated_topics_v3/profile_queries.py`
- Create: `tests/test_clock.py`
- Replace: `tests/test_profile_queries.py`
- Create: `tests/test_profiles.py`
- Modify: `config/profiles/tech_ai_creator.json`

**Interfaces:**
- Consumes: `UserProfile` from Task 1.
- Produces: `business_date(now: datetime) -> date`, `is_before_daily_cutoff(now: datetime) -> bool`, `load_profile(path: Path) -> UserProfile`, `save_profile(profile: UserProfile, path: Path) -> None`, `qianfan_query_units(value: str) -> int`, and `build_qianfan_query(profile: UserProfile) -> str`.

- [ ] **Step 1: Write failing clock and profile tests**

```python
def test_business_day_rolls_over_at_eight_am():
    assert business_date(datetime(2026, 7, 13, 7, 59, tzinfo=SHANGHAI)).isoformat() == "2026-07-12"
    assert business_date(datetime(2026, 7, 13, 8, 0, tzinfo=SHANGHAI)).isoformat() == "2026-07-13"


def test_qianfan_query_is_short_and_profile_derived():
    query = build_qianfan_query(sample_profile())
    assert "AI工具" in query
    assert "最新热点" in query
    assert qianfan_query_units(query) <= 72
```

Test JSON round-tripping and reject profiles whose `primary_keyword` is empty after trimming.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/test_clock.py tests/test_profiles.py tests/test_profile_queries.py -q`

Expected: FAIL because the modules and new schema do not exist.

- [ ] **Step 3: Implement Asia/Shanghai clock rules**

Use `zoneinfo.ZoneInfo("Asia/Shanghai")`. Convert aware datetimes to Shanghai time. Reject naive datetimes with `ValueError`. Before 08:00, subtract one calendar day for `business_date`.

- [ ] **Step 4: Implement profile JSON and compact Qianfan query construction**

Build the query from `primary_keyword`, `secondary_track`, a compact persona token, and `最新热点`. Deduplicate tokens in insertion order. Enforce the API's 72-unit rule with ASCII characters counting as one unit and Chinese characters counting as two; truncate only at whole-character boundaries.

- [ ] **Step 5: Update the sample profile and run tests**

Run: `uv run pytest tests/test_clock.py tests/test_profiles.py tests/test_profile_queries.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/heated_topics_v3/clock.py src/heated_topics_v3/profiles.py src/heated_topics_v3/profile_queries.py config/profiles/tech_ai_creator.json tests/test_clock.py tests/test_profiles.py tests/test_profile_queries.py
git commit -m "feat: add profile and business-day services"
```

### Task 3: Build the Filesystem Repository

**Files:**
- Create: `src/heated_topics_v3/storage.py`
- Create: `tests/test_storage.py`

**Interfaces:**
- Consumes: all Task 1 contracts.
- Produces: `FileRepository(root: Path)` with methods `daily_dir`, `save_raw`, `save_normalized`, `save_detail`, `save_collection_status`, `load_daily_snapshot`, `load_latest_user_bundle`, `load_user_bundle`, and `write_user_result_atomic`.

- [ ] **Step 1: Write failing storage layout tests**

Test exact paths under a temporary directory:

```python
repo.save_raw(date(2026, 7, 13), "baidu", "<html />", suffix="html")
assert (tmp_path / "daily_hot_lists/2026-07-13/raw/baidu.html").read_text("utf-8") == "<html />"
```

Test that normalized JSON never contains fields named `cookie`, `api_key`, `secret`, or authorization headers. Test that `write_user_result_atomic` leaves no final directory when its writer callback raises.

- [ ] **Step 2: Run the storage tests and confirm failure**

Run: `uv run pytest tests/test_storage.py -q`

Expected: FAIL because `FileRepository` does not exist.

- [ ] **Step 3: Implement deterministic paths and UTF-8 serialization**

Use `dataclasses.asdict` and JSON with `ensure_ascii=False`, two-space indentation, and trailing newline. Raw files live under `daily_hot_lists/<date>/raw`; normalized files under `normalized`; common detail files under `details`; profiles and user results use the approved design paths.

- [ ] **Step 4: Implement atomic user result writing**

Write to `<business-date>.tmp-<uuid>`, flush all files, then use `Path.replace` to publish the completed directory. If a complete final directory exists, return it without overwriting. Remove only the current operation's temporary directory after failure.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_storage.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/heated_topics_v3/storage.py tests/test_storage.py
git commit -m "feat: add hot topic filesystem repository"
```

### Task 4: Port Toutiao and Juejin Providers

**Files:**
- Create: `src/heated_topics_v3/providers/common.py`
- Create: `src/heated_topics_v3/providers/toutiao.py`
- Create: `src/heated_topics_v3/providers/juejin.py`
- Modify: `src/heated_topics_v3/providers/__init__.py`
- Create: `tests/providers/test_toutiao.py`
- Create: `tests/providers/test_juejin.py`
- Create: `tests/fixtures/toutiao_hot_board.json`
- Create: `tests/fixtures/toutiao_search.json`
- Create: `tests/fixtures/juejin_hot_rank.json`

**Interfaces:**
- Consumes: `HotItem`, `HeatMetrics`, and `ItemDetail` from Task 1.
- Produces: `ProviderCapture(raw_text: str, raw_suffix: str, items: tuple[HotItem, ...])` in `providers/common.py`; `ToutiaoProvider.collect_hot_list`, `ToutiaoProvider.search`, `ToutiaoProvider.fetch_detail`, `JuejinProvider.collect_hot_list`, and `JuejinProvider.fetch_detail`.

- [ ] **Step 1: Copy sanitized fixtures from verified old-project responses**

Fixtures must contain at least two rows, one numeric heat case, one missing-detail fallback, and no Cookies, tokens, or personal data.

- [ ] **Step 2: Write failing parser and fallback tests**

Assert the current public endpoints:

```python
TOUTIAO_HOT_BOARD_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
TOUTIAO_SEARCH_URL = "https://so.toutiao.com/search/"
JUEJIN_HOT_RANK_URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
JUEJIN_ARTICLE_DETAIL_URL = "https://api.juejin.cn/content_api/v1/article/detail"
```

Test that Toutiao search sends exactly one `primary_keyword`, classifies explicit engagement data, and rejects results older than 24 hours when a publication time exists. Test Juejin detail API preference and article-page fallback.

- [ ] **Step 3: Run focused provider tests and confirm failure**

Run: `uv run pytest tests/providers/test_toutiao.py tests/providers/test_juejin.py -q`

Expected: FAIL because the provider classes do not exist.

- [ ] **Step 4: Port and adapt the old verified parsing logic**

Adapt the existing implementations from the prior project without importing from outside this repository. Use injected `httpx.Client` or fetch callables in tests. Preserve raw response text at the orchestration boundary and keep provider outputs free of credentials.

Toutiao detail order is static article HTML, rendered article text, source summary, then title. Juejin detail order is detail API, article HTML, source summary, then title.

- [ ] **Step 5: Run provider tests**

Run: `uv run pytest tests/providers/test_toutiao.py tests/providers/test_juejin.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/heated_topics_v3/providers tests/providers/test_toutiao.py tests/providers/test_juejin.py tests/fixtures/toutiao_hot_board.json tests/fixtures/toutiao_search.json tests/fixtures/juejin_hot_rank.json
git commit -m "feat: add toutiao and juejin collectors"
```

### Task 5: Add Baidu Hot Search Provider

**Files:**
- Create: `src/heated_topics_v3/providers/baidu.py`
- Create: `tests/providers/test_baidu.py`
- Create: `tests/fixtures/baidu_realtime.html`

**Interfaces:**
- Consumes: Task 1 contracts.
- Produces: `BaiduProvider.collect_hot_list() -> ProviderCapture` and `parse_baidu_board(html: str, collected_at: str) -> tuple[HotItem, ...]`.

- [ ] **Step 1: Create a sanitized fixture with explanation variants**

Include one record with a full `large_*` explanation, one with only a short explanation, and one with no explanation. Include rank and hot-index markup for every row.

- [ ] **Step 2: Write failing Baidu parser tests**

```python
def test_baidu_uses_embedded_explanation_and_title_fallback():
    items = parse_baidu_board(fixture_text("baidu_realtime.html"), NOW)
    assert items[0].summary == "完整热点解释"
    assert items[2].summary == items[2].title
    assert items[0].heat.metric_name == "hot_index"
```

Also assert that publication time is `None`, the board rank is preserved, and the source URL is the item's Baidu search link.

- [ ] **Step 3: Run the test and confirm failure**

Run: `uv run pytest tests/providers/test_baidu.py -q`

Expected: FAIL because the provider does not exist.

- [ ] **Step 4: Implement server-rendered HTML parsing**

Parse the board at `https://top.baidu.com/board?tab=realtime`. Prefer the large explanation, then non-empty short explanation, then title. Deduplicate responsive duplicate explanation nodes inside the same record. Build `ItemDetail` without another network call and mark `title_only` only when the title fallback is used.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/providers/test_baidu.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/heated_topics_v3/providers/baidu.py tests/providers/test_baidu.py tests/fixtures/baidu_realtime.html
git commit -m "feat: add baidu hot search collector"
```

### Task 6: Port Cookie-Backed Weibo and Zhihu Providers

**Files:**
- Create: `src/heated_topics_v3/providers/weibo.py`
- Create: `src/heated_topics_v3/providers/zhihu.py`
- Create: `tests/providers/test_weibo.py`
- Create: `tests/providers/test_zhihu.py`
- Create: `tests/fixtures/weibo_hot_search.html`
- Create: `tests/fixtures/weibo_topic.html`
- Create: `tests/fixtures/zhihu_hot_list.json`
- Create: `tests/fixtures/zhihu_answers.json`
- Modify: `.env.example`

**Interfaces:**
- Consumes: Task 1 contracts.
- Produces: `WeiboProvider(cookie: str)`, `ZhihuProvider(cookie: str)`, their `collect_hot_list` and `fetch_detail` methods, and explicit `MissingCredentialError` / `AuthenticationExpiredError` failures.

- [ ] **Step 1: Add sanitized fixtures and failing tests**

Test ranked heat parsing, Weibo post-body extraction, Zhihu answer-body extraction, summary fallback, missing Cookie errors, and authentication-page detection. Assert exception messages name only the missing environment variable and never include the Cookie value.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/providers/test_weibo.py tests/providers/test_zhihu.py -q`

Expected: FAIL because the providers do not exist.

- [ ] **Step 3: Port the old provider logic with explicit credential boundaries**

Use `WEIBO_COOKIE` only in request headers created inside `WeiboProvider`; use `ZHIHU_COOKIE` only inside `ZhihuProvider`. Do not place headers in `HotItem.raw_payload` or provider error metadata. Limit Zhihu answer detail to five answers, matching the approved old behavior.

- [ ] **Step 4: Document environment fields**

Add empty `WEIBO_COOKIE`, `ZHIHU_COOKIE`, `QIANFAN_API_KEY`, and legacy `QIANFAN_SECRET_KEY` entries to `.env.example`, with comments that secrets must remain local.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/providers/test_weibo.py tests/providers/test_zhihu.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add .env.example src/heated_topics_v3/providers/weibo.py src/heated_topics_v3/providers/zhihu.py tests/providers/test_weibo.py tests/providers/test_zhihu.py tests/fixtures/weibo_hot_search.html tests/fixtures/weibo_topic.html tests/fixtures/zhihu_hot_list.json tests/fixtures/zhihu_answers.json
git commit -m "feat: add cookie-backed hot list collectors"
```

### Task 7: Implement Matching and Heat Classification

**Files:**
- Create: `src/heated_topics_v3/matching.py`
- Create: `tests/test_matching.py`

**Interfaces:**
- Consumes: `UserProfile`, `HotItem`, and `ItemDetail`.
- Produces: `matches_primary_keyword`, `classify_heat_level`, and `build_recommendation_item`.

- [ ] **Step 1: Write failing matching tests**

Cover case-insensitive Latin matching, direct Chinese substring matching, title/summary/detail search, official-board Level 1, explicit engagement Level 2, search-position-only Level 3, board-overlap promotion to Level 1, and `debunked` exclusion.

```python
def test_keyword_match_searches_detail_without_llm():
    assert matches_primary_keyword("AI工具", item(title="普通标题"), detail("适合职场的AI工具"))


def test_search_rank_alone_is_level_three():
    assert classify_heat_level(search_item(metric_name="search_rank")) == 3
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `uv run pytest tests/test_matching.py -q`

Expected: FAIL because the matching module does not exist.

- [ ] **Step 3: Implement deterministic matching and classification**

Normalize Unicode with NFKC and compare case-folded strings. Do not tokenize, expand aliases, or invoke a model. Treat `source_kind` values `hot_board`, `hot_search`, and `hot_rank` as Level 1. Treat explicit numeric metrics such as `hot_value`, `hot_index`, `views`, `reads`, `comments`, `likes`, and `engagement` as Level 2 when the record is not on a board. Treat only `search_rank` as Level 3.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_matching.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/matching.py tests/test_matching.py
git commit -m "feat: classify and match hot topics"
```

### Task 8: Add Qianfan Web Search Fallback

**Files:**
- Create: `src/heated_topics_v3/providers/qianfan.py`
- Create: `tests/providers/test_qianfan.py`
- Create: `tests/fixtures/qianfan_web_search.json`

**Interfaces:**
- Consumes: compact query from Task 2 and Task 1 contracts.
- Produces: `QianfanSearchProvider(api_key: str).search(query: str, now: datetime, top_k: int = 10) -> tuple[HotItem, ...]`.

- [ ] **Step 1: Write failing request and response tests**

Assert one POST to `https://qianfan.baidubce.com/v2/ai_search/web_search`, Bearer authentication, `search_source="baidu_search_v2"`, web `top_k=10`, and a `page_time` range covering exactly the previous 24 hours. Assert API keys never appear in returned raw payloads or exception text.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/providers/test_qianfan.py -q`

Expected: FAIL because the provider does not exist.

- [ ] **Step 3: Implement one-call search and reference normalization**

Normalize each reference into a Level-3-compatible `HotItem` with title, URL, source summary, and page time. Discard results older than 24 hours when page time exists. Deduplicate exact URLs within the Qianfan response. Return at most ten items; later orchestration selects at most five.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/providers/test_qianfan.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/providers/qianfan.py tests/providers/test_qianfan.py tests/fixtures/qianfan_web_search.json
git commit -m "feat: add qianfan potential-topic search"
```

### Task 9: Orchestrate Full Daily Collection and Detail Batches

**Files:**
- Create: `src/heated_topics_v3/collection.py`
- Create: `tests/test_collection.py`

**Interfaces:**
- Consumes: platform providers from Tasks 4-6, Task 1 contracts, and `FileRepository`.
- Produces: `ProviderSet(toutiao, baidu, juejin, weibo, zhihu)` as a frozen dataclass; `DetailCoordinator.prioritize(platform: str, item_ids: tuple[str, ...]) -> tuple[ItemDetail, ...]`; and `collect_daily_snapshot(now: datetime, providers: ProviderSet, repository: FileRepository, sleeper: Callable = time.sleep, random_source: Random | None = None) -> DailySnapshot`.

- [ ] **Step 1: Write failing orchestration tests with fake providers**

Test that all five providers run independently, raw data is saved before normalized data, Baidu does not issue detail requests, Toutiao/Juejin detail concurrency never exceeds three, Weibo/Zhihu never exceed two, and Cookie failure does not fail the other platforms.

Test batch scheduling with an injected no-op sleeper and deterministic random source: five Weibo and five Zhihu records per batch, eight-to-ten-minute requested delays between batches, and priority item IDs processed before remaining queued IDs.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/test_collection.py -q`

Expected: FAIL because collection orchestration does not exist.

- [ ] **Step 3: Implement isolated board collection**

Represent each provider call as a `ProviderCapture(raw_text, raw_suffix, items)`. Catch platform exceptions, write `PlatformCollectionStatus`, and continue. Never create a normalized platform file from a failed raw capture.

- [ ] **Step 4: Implement detail execution policies**

Use `ThreadPoolExecutor(max_workers=3)` independently for Toutiao and Juejin. Use two worker queues for Weibo and Zhihu, batch size five, `ThreadPoolExecutor(max_workers=2)`, and injected delay scheduling. Save each completed detail immediately so interrupted runs retain progress.

- [ ] **Step 5: Implement priority detail insertion**

Maintain a thread-safe set of completed/in-flight IDs. A priority request moves requested pending IDs ahead of regular batches. If it fails, persist a summary/title fallback once and mark it complete so the batch does not repeat it.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_collection.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/heated_topics_v3/collection.py tests/test_collection.py
git commit -m "feat: orchestrate daily hot list collection"
```

### Task 10: Render Markdown, JSON, and Minimal TXT

**Files:**
- Create: `src/heated_topics_v3/reporting.py`
- Create: `tests/test_reporting.py`

**Interfaces:**
- Consumes: `RecommendationBundle`.
- Produces: `render_markdown`, `serialize_bundle`, `topic_txt_filename`, and `render_topic_txt`.

- [ ] **Step 1: Write failing output tests**

Assert fixed platform order, Level 1/2 labels in the formal section, a separate Level 3 section, and non-personalized labeling for general fallback records. Assert TXT output has exactly these labels and no URL, evidence, fact-status, or internal IDs:

```text
标题：
平台：
热点等级：
发布时间：
采集时间：

详细内容：
```

Assert filenames use `<platform>_<three-digit-sequence>.txt`, not titles.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/test_reporting.py -q`

Expected: FAIL because reporting functions do not exist.

- [ ] **Step 3: Implement deterministic renderers**

Keep all rich evidence, query metadata, factual status, content status, and source URLs in JSON. Markdown includes uncertainty notices, while TXT stays minimal. Use `平台未提供` for absent publication times.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_reporting.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/reporting.py tests/test_reporting.py
git commit -m "feat: render recommendation artifacts"
```

### Task 11: Implement Once-Per-Day Recommendation Generation

**Files:**
- Create: `src/heated_topics_v3/recommendation.py`
- Create: `tests/test_recommendation.py`

**Interfaces:**
- Consumes: profile, business-day, repository, matching, provider, collection priority, and reporting interfaces from Tasks 2-10.
- Produces: frozen `RecommendationServices(toutiao: ToutiaoProvider, qianfan: QianfanSearchProvider | None, details: DetailCoordinator)` and `generate_user_recommendations(user_id: str, now: datetime, repository: FileRepository, services: RecommendationServices) -> RecommendationBundle`.

- [ ] **Step 1: Write failing happy-path and cache tests**

Create fake snapshots with matched Level 1 records on multiple platforms and a Toutiao search Level 2 record. Assert fixed platform order, allowed cross-platform duplicates, no Qianfan call, one result directory, and a second same-day call returning `existing` without provider calls.

- [ ] **Step 2: Write failing pre-08:00 tests**

Assert that a pre-08:00 request returns the latest historical bundle with status `existing`; if none exists, return `not_ready`. Assert pre-08:00 access does not create a current-date result directory.

- [ ] **Step 3: Write failing no-match fallback tests**

Assert exactly the top three valid Toutiao plus top two valid Baidu records when available, filling shortages from the other primary source. Assert one Qianfan call, at most five Level 3 results, and no forced padding.

- [ ] **Step 4: Run tests and confirm failure**

Run: `uv run pytest tests/test_recommendation.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 5: Implement a per-user/date generation lock**

Use an in-process lock registry keyed by `(user_id, business_date)` and re-check storage after acquiring the lock. Do not hold a global lock during provider calls. Publish results through `write_user_result_atomic`.

- [ ] **Step 6: Implement personalized generation**

Load all successful platform snapshots and details; match only `primary_keyword`; fetch pending matched Weibo/Zhihu details through the priority interface; run exactly one Toutiao keyword search; classify results; exclude `debunked`; and preserve platform/source order.

- [ ] **Step 7: Implement no-match fallback**

Select general hot records from Toutiao and Baidu only. Build and send one compact Qianfan query only on this path. Retain at most five results. Complete successfully even when Qianfan fails.

- [ ] **Step 8: Render and atomically save all artifacts**

Write `report.md`, `result.json`, and one `topics/<platform>_<sequence>.txt` per formal, general, or potential result. Return `no_result` only when personalized, general, and potential collections are all empty.

- [ ] **Step 9: Run tests**

Run: `uv run pytest tests/test_recommendation.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add src/heated_topics_v3/recommendation.py tests/test_recommendation.py
git commit -m "feat: generate cached daily recommendations"
```

### Task 12: Add Python API, CLI, and End-to-End Manual Verification

**Files:**
- Create: `src/heated_topics_v3/cli.py`
- Modify: `src/heated_topics_v3/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/test_cli.py`
- Modify: `README.md`
- Create: `docs/specs/hot-topic-workflow-implementation-report.md`

**Interfaces:**
- Consumes: Tasks 1-11.
- Produces: public `collect_daily_snapshot`, `generate_user_recommendations`, and CLI commands `heated-topics collect-daily` and `heated-topics generate-user`.

- [ ] **Step 1: Write failing CLI tests**

Use injected service factories to assert:

```text
heated-topics collect-daily --data-root <path>
heated-topics generate-user --data-root <path> --profile <profile.json>
```

Both commands emit one JSON status object to stdout and use nonzero exit codes only for unrecovered `failed` results.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL because the entry point does not exist.

- [ ] **Step 3: Implement CLI and public exports**

Add this project entry point:

```toml
[project.scripts]
heated-topics = "heated_topics_v3.cli:main"
```

Load `.env`, construct providers from environment variables, and avoid printing credential-bearing exception objects. Export the two main service functions from `__init__.py`.

- [ ] **Step 4: Document manual setup and commands**

README must explain profile fields, `.env` names, output directories, Cookie failure isolation, and the absence of automatic scheduling in this iteration.

- [ ] **Step 5: Run the complete automated test suite**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Run the real five-platform daily collection**

Run:

```powershell
uv run heated-topics collect-daily --data-root data
```

Expected:

- Toutiao, Baidu, and Juejin write raw, normalized, and detail artifacts.
- Weibo and Zhihu do the same when valid Cookies are present; otherwise their isolated failures appear in `collection_status.json`.
- No credential value appears in console output or stored files.

- [ ] **Step 7: Inspect record and detail counts**

Run:

```powershell
Get-ChildItem data\daily_hot_lists\$(Get-Date -Format yyyy-MM-dd)\normalized
Get-ChildItem data\daily_hot_lists\$(Get-Date -Format yyyy-MM-dd)\details | Measure-Object
```

Expected: one normalized file per successful platform and one detail artifact per normalized item. Counts are observed and recorded; the test does not require exactly 241 records.

- [ ] **Step 8: Generate one real user result twice**

Run:

```powershell
uv run heated-topics generate-user --data-root data --profile config\profiles\tech_ai_creator.json
uv run heated-topics generate-user --data-root data --profile config\profiles\tech_ai_creator.json
```

Expected: the first call returns `generated` or `no_result`; the second returns `existing` and performs no new search calls.

- [ ] **Step 9: Inspect artifacts and secret leakage**

Run:

```powershell
Get-ChildItem data\user_results -Recurse
rg -l "QIANFAN_API_KEY|QIANFAN_SECRET_KEY|WEIBO_COOKIE|ZHIHU_COOKIE|Authorization:|Cookie:" data
```

Expected: Markdown, JSON, and TXT artifacts exist; the secret-name scan returns no files.

- [ ] **Step 10: Commit**

```powershell
git add src/heated_topics_v3/__init__.py src/heated_topics_v3/cli.py pyproject.toml tests/test_cli.py README.md docs/specs/hot-topic-workflow-implementation-report.md
git commit -m "feat: expose complete hot topic workflow"
```

## Final Verification Gate

- [ ] Run `uv run pytest -q` and record the passing count.
- [ ] Run `git status --short` and confirm only intentional generated test data is untracked; keep real `data/` outputs out of Git.
- [ ] Confirm every successful platform has raw, normalized, and detail artifacts.
- [ ] Confirm the generated Markdown and JSON list platforms in the approved fixed order.
- [ ] Confirm every TXT contains only the approved fields.
- [ ] Confirm the second same-day user call returns `existing`.
- [ ] Confirm no secret values or credential headers appear under `data/`.
- [ ] Update the implementation report with actual platform counts, failures, elapsed times, and fallback behavior observed during the real run.
