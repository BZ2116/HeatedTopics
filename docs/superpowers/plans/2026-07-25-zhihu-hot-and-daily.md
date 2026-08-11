# 知乎站内热榜与知乎日报双数据源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 cached-news 工作流中新增需要本地 `ZHIHU_COOKIE` 的知乎站内真实热榜，并完善匿名知乎日报的置顶推荐，使两个 Provider 都能产出带完整正文、热点证据和稳定缓存的独立用户结果。

**Architecture:** `ZhihuHotProvider` 使用 `httpx` 和本地 Cookie，优先解析知乎热榜 JSON API，契约变化时回退 `/hot` HTML；问题详情优先使用 question/answers API，契约变化时回退问题页 HTML。结构化问题统计和回答 metadata 随 `ItemDetail` 持久化，正文保存为现有稳定文本文件；`zhihu_daily` 继续匿名访问，并增加 `top_stories`。不支持搜索的 `zhihu_hot` 通过 Provider 能力标记跳过普通搜索，并在当日采集不可用时使用不超过 48 小时的有效快照。

**Tech Stack:** Python 3.10+、`httpx`、stdlib `json` / `html.parser` / `re`、`python-dotenv`、`pytest`、现有 `FileRepository` cached-news 工作流。

## Global Constraints

- `zhihu_hot` 必须只从本地环境变量 `ZHIHU_COOKIE` 读取认证信息；不得读取浏览器 Cookie、密码、本地存储或会话文件。
- Cookie 不得出现在 Git、日志、异常消息、fixture、`raw_payload`、缓存、smoke 结果或 `collection_status.json`。
- Cookie 只能发送给 `https://www.zhihu.com` 或 `https://zhihu.com`，不得随重定向发送给其他域名。
- `zhihu_hot` 认证失败不得影响 `zhihu_daily` 或其他平台。
- 热榜 API 成功响应契约变化时才回退 HTML；`401`、`403` 或 `/signin` 跳转必须直接报告认证失效。
- 站内热榜必须保留正数官方排名、正数官方热度、问题 ID 和问题 URL。
- 默认最多保存 5 个热门回答；回答少于 5 个时保存实际数量，不得补造。
- `zhihu_hot` 不调用普通站内搜索，不把普通搜索结果冒充真实热榜。
- `zhihu_daily` 保持匿名访问，保留最近 7 天、最多 60 个去重候选、最多 20 个正式结果的现有边界。
- 合格详情至少 80 个有效字符，并至少包含 2 个真实段落或 3 个完整句子；不能用标题、摘要、登录页或页面框架代替正文。
- 当前完整测试基线是 `322 passed`；每项任务必须保持全部回归测试通过。
- 实现分支为 `feature/baidu-zhihu-daily-mvp`，设计基准提交为 `2bcf8ba`。

---

## File Structure

```text
src/heated_topics_v3/
├── contracts.py                     # ItemDetail 增加结构化 metadata
├── storage.py                       # 详情 JSON sidecar 的保存和读取
├── collection.py                    # 保存/恢复完整 ItemDetail
├── discovery.py                     # supports_search=False 与 48 小时快照回退
├── recommendation.py                # 注册 zhihu_hot 展示顺序
├── cli.py                           # Cookie 加载、Provider 构造、认证健康检查命令
└── providers/
    ├── common.py                    # 认证异常和 NEWS_PLATFORMS
    ├── zhihu_hot.py                 # 真实热榜、问题详情、回答和排序
    ├── zhihu_daily.py               # latest + top_stories + archive
    └── __init__.py                  # Provider export

tests/
├── fixtures/
│   ├── zhihu_hot_api.json
│   ├── zhihu_hot_page.html
│   ├── zhihu_hot_question.json
│   ├── zhihu_hot_answers.json
│   ├── zhihu_hot_question_page.html
│   ├── zhihu_hot_signin.html
│   └── zhihu_daily_latest.json       # 扩展 top_stories
├── providers/
│   ├── test_provider_contracts.py
│   ├── test_zhihu_hot.py
│   └── test_zhihu_daily.py
├── test_contracts.py
├── test_storage.py
├── test_discovery.py
├── test_news_collection.py
├── test_news_recommendation.py
├── test_news_cli.py
└── test_news_smoke_validator.py

tools/
└── validate_news_smoke.py            # 检查双知乎来源、限制和凭据泄漏

docs/specs/
└── zhihu-dual-source-implementation-report.md
```

---

### Task 1: Persist Structured Item Detail Metadata

**Files:**
- Modify: `src/heated_topics_v3/contracts.py`
- Modify: `src/heated_topics_v3/storage.py`
- Modify: `src/heated_topics_v3/collection.py`
- Modify: `tests/test_contracts.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_news_collection.py`

**Interfaces:**
- Produces: `ItemDetail.metadata: Mapping[str, Any]`.
- Produces: `FileRepository.save_item_detail_metadata(business_date: BusinessDate, platform: str, detail: ItemDetail) -> Path`.
- Produces: `FileRepository.load_item_detail_metadata(business_date: BusinessDate, platform: str, item_id: str) -> ItemDetail | None`.
- Preserves: existing `save_stable_detail(..., content: str)` text files for backward compatibility.

- [ ] **Step 1: Write failing metadata contract and persistence tests**

Add to `tests/test_contracts.py`:

```python
def test_item_detail_metadata_defaults_empty_and_is_immutable_contract():
    from heated_topics_v3.contracts import ItemDetail

    detail = ItemDetail(
        item_id="zhihu_hot_question_1",
        content="第一段完整正文。\n\n第二段完整正文。",
        content_status="full_text",
        publication_time=None,
        collected_at="2026-07-25T08:00:00+08:00",
        source_url="https://www.zhihu.com/question/1",
        fetch_status="success",
    )
    assert detail.metadata == {}
```

Add to `tests/test_storage.py`:

```python
def test_item_detail_metadata_round_trip(tmp_path):
    from heated_topics_v3.contracts import ItemDetail
    from heated_topics_v3.storage import FileRepository

    repository = FileRepository(tmp_path)
    detail = ItemDetail(
        item_id="zhihu_hot_question_1",
        content="问题描述。\n\n热门回答正文。",
        content_status="full_text",
        publication_time="2026-07-25T10:27:00+08:00",
        collected_at="2026-07-25T12:00:00+08:00",
        source_url="https://www.zhihu.com/question/1",
        fetch_status="success",
        metadata={
            "question": {"view_count": 1985997, "answer_count": 583},
            "answers": [{"answer_id": "11", "author": "示例作者", "voteup_count": 1551}],
        },
    )

    path = repository.save_item_detail_metadata(
        "2026-07-25", "zhihu_hot", detail
    )
    loaded = repository.load_item_detail_metadata(
        "2026-07-25", "zhihu_hot", detail.item_id
    )

    assert path.name == "zhihu_hot_zhihu_hot_question_1.json"
    assert loaded == detail
```

Add to `tests/test_news_collection.py`:

```python
def test_news_collection_reuses_detail_metadata_sidecar(tmp_path):
    repository = FileRepository(tmp_path)
    item = _item(
        platform="sina_news",
        item_id="sina_news_metadata",
        rank=1,
        metrics={"comments": 20.0},
    )
    detail = ItemDetail(
        item_id=item.item_id,
        content=_LONG_BODY,
        content_status="full_text",
        publication_time=None,
        collected_at=COLLECTED_AT,
        source_url=item.url,
        fetch_status="success",
        metadata={"question": {"view_count": 42}},
    )
    provider = FakeNewsProvider(
        "sina_news",
        (item,),
        detail_payloads={item.item_id: detail},
    )

    collect_news_daily(NOW, repository, {"sina_news": provider})
    provider.detail_calls.clear()
    collect_news_daily(NOW, repository, {"sina_news": provider})

    eligible = repository.load_eligible(BUSINESS_DATE, "sina_news")
    assert eligible[0].detail.metadata == {"question": {"view_count": 42}}
    assert provider.detail_calls == []
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
uv run pytest tests/test_contracts.py tests/test_storage.py tests/test_news_collection.py -q
```

Expected: failures because `ItemDetail` has no `metadata` field and `FileRepository` has no metadata sidecar methods.

- [ ] **Step 3: Add the metadata field and JSON sidecar methods**

Modify `ItemDetail` in `src/heated_topics_v3/contracts.py`:

```python
@dataclass(frozen=True)
class ItemDetail:
    item_id: str
    content: str
    content_status: ContentStatus
    publication_time: str | None
    collected_at: str
    source_url: str
    fetch_status: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Add to `FileRepository` in `src/heated_topics_v3/storage.py`:

```python
def save_item_detail_metadata(
    self,
    business_date: BusinessDate,
    platform: str,
    detail: ItemDetail,
) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", detail.item_id)
    path = self.daily_dir(business_date) / "details" / f"{platform}_{safe_id}.json"
    return self.write_json(path, detail)

def load_item_detail_metadata(
    self,
    business_date: BusinessDate,
    platform: str,
    item_id: str,
) -> ItemDetail | None:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item_id)
    path = self.daily_dir(business_date) / "details" / f"{platform}_{safe_id}.json"
    if not path.is_file():
        return None
    return _item_detail_from_dict(self._read_json(path))
```

Import `re` in `storage.py` if it is not already imported. Extend `_item_detail_from_dict`:

```python
def _item_detail_from_dict(data: Mapping[str, Any]) -> ItemDetail:
    return ItemDetail(
        item_id=str(data["item_id"]),
        content=str(data["content"]),
        content_status=data["content_status"],
        publication_time=data.get("publication_time"),
        collected_at=str(data["collected_at"]),
        source_url=str(data["source_url"]),
        fetch_status=str(data["fetch_status"]),
        metadata=dict(data.get("metadata") or {}),
    )
```

In `_collect_news_platform`, save the JSON sidecar immediately after the existing stable text detail:

```python
repository.save_stable_detail(
    business_date, platform, item.item_id, detail.content
)
repository.save_item_detail_metadata(
    business_date, platform, detail
)
```

In `_load_cached_news_details`, prefer the JSON sidecar:

```python
metadata_detail = repository.load_item_detail_metadata(
    business_date, platform, item.item_id
)
if metadata_detail is not None:
    cached[item.item_id] = metadata_detail
    continue
```

Retain the existing `.txt` fallback so old snapshots remain readable.

- [ ] **Step 4: Run focused and full regression tests**

Run:

```powershell
uv run pytest tests/test_contracts.py tests/test_storage.py tests/test_news_collection.py -q
uv run pytest -q
git diff --check
```

Expected: focused tests pass; full suite passes with more than 322 tests.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/contracts.py src/heated_topics_v3/storage.py src/heated_topics_v3/collection.py tests/test_contracts.py tests/test_storage.py tests/test_news_collection.py
git commit -m "feat: persist structured detail metadata"
```

---

### Task 2: Add Zhihu Authentication Boundaries and Health Check Provider

**Files:**
- Create: `src/heated_topics_v3/providers/zhihu_hot.py`
- Modify: `src/heated_topics_v3/providers/common.py`
- Create: `tests/providers/test_zhihu_hot.py`
- Create: `tests/fixtures/zhihu_hot_signin.html`
- Modify: `tests/providers/test_provider_contracts.py`

**Interfaces:**
- Produces: `MissingCredentialError(variable_name: str)`.
- Produces: `AuthenticationExpiredError(variable_name: str)`.
- Produces: `AuthenticationBlockedError(variable_name: str)`.
- Produces: `ZhihuHotProvider(client: httpx.Client, cookie: str)`.
- Produces: `ZhihuHotProvider.check_auth() -> Literal["valid", "missing", "expired", "blocked", "contract_changed"]`.
- Produces: `ZhihuHotProvider.supports_search = False`.

- [ ] **Step 1: Create the sign-in fixture and failing authentication tests**

Create `tests/fixtures/zhihu_hot_signin.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head><title>知乎 - 登录</title></head>
  <body>
    <main><a href="/signin">登录知乎，发现更多可信赖的解答</a></main>
  </body>
</html>
```

Create the initial `tests/providers/test_zhihu_hot.py`:

```python
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-25T12:00:00+08:00"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_missing_cookie_has_explicit_health_status():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(_client(lambda request: httpx.Response(500)), "")
    assert provider.check_auth() == "missing"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_http_failures_are_expired_without_leaking_cookie(status):
    from heated_topics_v3.providers.common import AuthenticationExpiredError
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    cookie = "z_c0=private-cookie-value"
    provider = ZhihuHotProvider(
        _client(lambda request: httpx.Response(status, request=request)),
        cookie,
    )

    with pytest.raises(AuthenticationExpiredError) as captured:
        provider.collect_hot_list(NOW)
    assert cookie not in str(captured.value)
    assert provider.check_auth() == "expired"


def test_signin_redirect_is_expired():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "/signin?next=%2Fhot"},
            request=request,
        )

    provider = ZhihuHotProvider(_client(handler), "z_c0=local")
    assert provider.check_auth() == "expired"


def test_signin_html_is_expired():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    signin = (FIXTURES / "zhihu_hot_signin.html").read_text(encoding="utf-8")
    provider = ZhihuHotProvider(
        _client(
            lambda request: httpx.Response(
                200, text=signin, request=request,
                headers={"Content-Type": "text/html"},
            )
        ),
        "z_c0=local",
    )
    assert provider.check_auth() == "expired"


def test_rate_limit_is_reported_as_blocked():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(
        _client(lambda request: httpx.Response(429, request=request)),
        "z_c0=local",
    )
    assert provider.check_auth() == "blocked"


def test_provider_never_sends_cookie_to_untrusted_host():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(_client(lambda request: httpx.Response(200)), "z_c0=local")
    with pytest.raises(ValueError, match="untrusted zhihu URL"):
        provider._get("https://example.com/article")


def test_transient_gateway_failure_retries_once():
    from heated_topics_v3.providers.zhihu_hot import (
        ZHIHU_HOT_API_URL,
        ZhihuHotProvider,
    )

    calls = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text='{"data":[]}', request=request)

    provider = ZhihuHotProvider(_client(handler), "z_c0=local")
    assert provider._get(ZHIHU_HOT_API_URL).status_code == 200
    assert calls == 2


def test_zhihu_hot_provider_contract_attributes():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(_client(lambda request: httpx.Response(500)), "")
    assert provider.platform == "zhihu_hot"
    assert provider.supports_search is False
    assert provider.weights == {"hot_score": 1.0}
    assert provider.absolute_floors == {"hot_score": 1.0}
```

Add the same attribute assertions to `tests/providers/test_provider_contracts.py`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py tests/providers/test_provider_contracts.py -q
```

Expected: import failures for `zhihu_hot`, `MissingCredentialError`, and `AuthenticationExpiredError`.

- [ ] **Step 3: Implement sanitized exceptions and the provider request boundary**

Add to `src/heated_topics_v3/providers/common.py`:

```python
class MissingCredentialError(RuntimeError):
    def __init__(self, variable_name: str) -> None:
        super().__init__(variable_name)
        self.variable_name = variable_name


class AuthenticationExpiredError(RuntimeError):
    def __init__(self, variable_name: str) -> None:
        super().__init__(variable_name)
        self.variable_name = variable_name


class AuthenticationBlockedError(RuntimeError):
    def __init__(self, variable_name: str) -> None:
        super().__init__(variable_name)
        self.variable_name = variable_name
```

Create `src/heated_topics_v3/providers/zhihu_hot.py` with these constants and the authentication foundation:

```python
from __future__ import annotations

from typing import Literal, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import (
    AuthenticationExpiredError,
    AuthenticationBlockedError,
    MissingCredentialError,
    ProviderCapture,
    ProviderContractError,
)

ZHIHU_COOKIE_ENV = "ZHIHU_COOKIE"
ZHIHU_HOT_API_URL = (
    "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"
    "?limit=50&desktop=true"
)
ZHIHU_HOT_PAGE_URL = "https://www.zhihu.com/hot"
TRUSTED_ZHIHU_HOSTS = frozenset({"www.zhihu.com", "zhihu.com"})
TRANSIENT_STATUSES = frozenset({502, 503, 504})
MAX_REQUEST_ATTEMPTS = 2


class ZhihuHotProvider:
    platform = "zhihu_hot"
    supports_search = False
    weights: Mapping[str, float] = {"hot_score": 1.0}
    absolute_floors: Mapping[str, float] = {"hot_score": 1.0}

    def __init__(self, client: httpx.Client, cookie: str):
        self.client = client
        self.cookie = cookie.strip()

    def _get(self, url: str) -> httpx.Response:
        if not self.cookie:
            raise MissingCredentialError(ZHIHU_COOKIE_ENV)
        current = url
        for _redirect in range(4):
            host = (urlsplit(current).hostname or "").casefold()
            if host not in TRUSTED_ZHIHU_HOSTS:
                raise ValueError("untrusted zhihu URL")
            for attempt in range(MAX_REQUEST_ATTEMPTS):
                response = self.client.get(
                    current,
                    follow_redirects=False,
                    headers={
                        "Cookie": self.cookie,
                        "Referer": ZHIHU_HOT_PAGE_URL,
                        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                    },
                )
                if (
                    response.status_code not in TRANSIENT_STATUSES
                    or attempt + 1 == MAX_REQUEST_ATTEMPTS
                ):
                    break
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                current = str(response.url.join(location))
                if urlsplit(current).path.casefold().startswith("/signin"):
                    raise AuthenticationExpiredError(ZHIHU_COOKIE_ENV)
                continue
            if response.status_code in {401, 403}:
                raise AuthenticationExpiredError(ZHIHU_COOKIE_ENV)
            if response.status_code in {418, 429}:
                raise AuthenticationBlockedError(ZHIHU_COOKIE_ENV)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").casefold()
            body = response.text.casefold()
            if (
                "text/html" in content_type
                and "/signin" in body
                and ("登录" in response.text or "sign in" in body)
            ):
                raise AuthenticationExpiredError(ZHIHU_COOKIE_ENV)
            return response
        raise ProviderContractError("zhihu redirect limit exceeded")

    def check_auth(
        self,
    ) -> Literal["valid", "missing", "expired", "blocked", "contract_changed"]:
        if not self.cookie:
            return "missing"
        try:
            self.collect_hot_list("1970-01-01T00:00:00+08:00")
        except AuthenticationExpiredError:
            return "expired"
        except AuthenticationBlockedError:
            return "blocked"
        except httpx.HTTPStatusError:
            return "blocked"
        except ProviderContractError:
            return "contract_changed"
        return "valid"
```

For this task, define `collect_hot_list`, `fetch_detail`, `search`, and `enrich_metrics` with valid signatures. `collect_hot_list` may raise `ProviderContractError("zhihu hot parser not implemented")`; `search` must already return `ProviderCapture("", ".json", ())`; `enrich_metrics` returns `tuple(items)`. Task 3 replaces the parser stub.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py tests/providers/test_provider_contracts.py -q
uv run pytest -q
git diff --check
```

Expected: authentication tests pass and the full suite remains green.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/providers/common.py src/heated_topics_v3/providers/zhihu_hot.py tests/providers/test_zhihu_hot.py tests/providers/test_provider_contracts.py tests/fixtures/zhihu_hot_signin.html
git commit -m "feat: define zhihu hot authentication boundary"
```

---

### Task 3: Parse the Real Zhihu Hot Board With API and HTML Fallback

**Files:**
- Modify: `src/heated_topics_v3/providers/zhihu_hot.py`
- Modify: `tests/providers/test_zhihu_hot.py`
- Create: `tests/fixtures/zhihu_hot_api.json`
- Create: `tests/fixtures/zhihu_hot_page.html`

**Interfaces:**
- Produces: `ZhihuHotProvider.parse_api_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]`.
- Produces: `ZhihuHotProvider.parse_html_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]`.
- Produces: `parse_hot_score(label: str) -> int | None`.
- Guarantees: API and HTML parsers emit identical normalized contracts.

- [ ] **Step 1: Add exact sanitized fixtures**

Create `tests/fixtures/zhihu_hot_api.json`:

```json
{
  "data": [
    {
      "type": "hot_list_feed",
      "target": {
        "id": 2064289475916560021,
        "title_area": {
          "text": "示例平台因垄断行为被处罚，会带来哪些影响？"
        },
        "excerpt_area": {
          "text": "监管机构公布处罚决定，相关行业规则可能发生变化。"
        },
        "metrics_area": {
          "text": "2114 万热度"
        },
        "link": {
          "url": "https://www.zhihu.com/question/2064289475916560021"
        }
      }
    },
    {
      "type": "hot_list_feed",
      "target": {
        "id": 2063947146085097774,
        "title_area": {
          "text": "如何评价一项新的数学研究成果？"
        },
        "excerpt_area": {
          "text": "研究团队在国际会议上公布了最新成果。"
        },
        "metrics_area": {
          "text": "435 万热度"
        },
        "link": {
          "url": "https://www.zhihu.com/question/2063947146085097774"
        }
      }
    }
  ],
  "paging": {
    "is_end": true
  }
}
```

Create `tests/fixtures/zhihu_hot_page.html` with both hydration JSON and rendered card markup:

```html
<!doctype html>
<html lang="zh-CN">
  <body>
    <script id="js-initialData" type="text/json">
      {
        "initialState": {
          "topstory": {
            "hotList": [
              {
                "id": 2064289475916560021,
                "title": "示例平台因垄断行为被处罚，会带来哪些影响？",
                "excerpt": "监管机构公布处罚决定，相关行业规则可能发生变化。",
                "detailText": "2114 万热度",
                "url": "https://www.zhihu.com/question/2064289475916560021"
              },
              {
                "id": 2063947146085097774,
                "title": "如何评价一项新的数学研究成果？",
                "excerpt": "研究团队在国际会议上公布了最新成果。",
                "detailText": "435 万热度",
                "url": "https://www.zhihu.com/question/2063947146085097774"
              }
            ]
          }
        }
      }
    </script>
    <main>
      <section data-za-detail-view-path-module="HotItem">
        <span class="HotItem-rank">1</span>
        <a href="/question/2064289475916560021">
          <h2>示例平台因垄断行为被处罚，会带来哪些影响？</h2>
        </a>
        <p>监管机构公布处罚决定，相关行业规则可能发生变化。</p>
        <span>2114 万热度</span>
      </section>
      <section data-za-detail-view-path-module="HotItem">
        <span class="HotItem-rank">2</span>
        <a href="/question/2063947146085097774">
          <h2>如何评价一项新的数学研究成果？</h2>
        </a>
        <p>研究团队在国际会议上公布了最新成果。</p>
        <span>435 万热度</span>
      </section>
    </main>
  </body>
</html>
```

- [ ] **Step 2: Write failing parser and fallback tests**

Append to `tests/providers/test_zhihu_hot.py`:

```python
def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_hot_score_parses_chinese_units():
    from heated_topics_v3.providers.zhihu_hot import parse_hot_score

    assert parse_hot_score("2114 万热度") == 21_140_000
    assert parse_hot_score("1.2 亿热度") == 120_000_000
    assert parse_hot_score("9876 热度") == 9_876
    assert parse_hot_score("没有热度") is None


def test_api_and_html_hot_lists_have_same_contract():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    api = ZhihuHotProvider.parse_api_hot_list(
        _fixture("zhihu_hot_api.json"), NOW
    )
    html = ZhihuHotProvider.parse_html_hot_list(
        _fixture("zhihu_hot_page.html"), NOW
    )

    projection = lambda items: [
        (
            item.item_id,
            item.title,
            item.url,
            item.rank,
            item.heat.value,
            item.summary,
        )
        for item in items
    ]
    assert projection(api) == projection(html)
    assert api[0].item_id == "zhihu_hot_question_2064289475916560021"
    assert api[0].heat.metrics == {"hot_score": 21_140_000}


def test_collect_uses_api_when_contract_is_valid():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=_fixture("zhihu_hot_api.json"), request=request)

    capture = ZhihuHotProvider(_client(handler), "z_c0=local").collect_hot_list(NOW)
    assert capture.metadata == {"source": "api"}
    assert capture.raw_suffix == ".json"
    assert len(capture.items) == 2
    assert len(calls) == 1


def test_collect_falls_back_to_html_only_on_api_contract_change():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        body = "{}" if request.url.path.startswith("/api/") else _fixture("zhihu_hot_page.html")
        return httpx.Response(200, text=body, request=request)

    capture = ZhihuHotProvider(_client(handler), "z_c0=local").collect_hot_list(NOW)
    assert capture.metadata == {"source": "html_fallback"}
    assert capture.raw_suffix == ".html"
    assert calls == ["/api/v3/feed/topstory/hot-lists/total", "/hot"]


@pytest.mark.parametrize("raw", ["{}", '{"data":[]}', '{"data":[{"target":{}}]}'])
def test_api_parser_fails_closed(raw):
    from heated_topics_v3.providers.common import ProviderContractError
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    with pytest.raises(ProviderContractError):
        ZhihuHotProvider.parse_api_hot_list(raw, NOW)
```

- [ ] **Step 3: Run parser tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py -q
```

Expected: failures for missing parsers and missing `parse_hot_score`.

- [ ] **Step 4: Implement normalized parsers and collection fallback**

Implement `parse_hot_score` using `Decimal` to avoid binary rounding:

```python
_HOT_SCORE_RE = re.compile(r"([\d.]+)\s*(万|亿)?\s*热度")
_HOT_MULTIPLIERS = {"": 1, "万": 10_000, "亿": 100_000_000}


def parse_hot_score(label: str) -> int | None:
    match = _HOT_SCORE_RE.search(label)
    if match is None:
        return None
    try:
        return int(Decimal(match.group(1)) * _HOT_MULTIPLIERS[match.group(2) or ""])
    except (InvalidOperation, KeyError):
        return None
```

Add a single normalizer used by both parsers:

```python
def _hot_item(
    *,
    question_id: object,
    title: object,
    summary: object,
    url: object,
    heat_label: object,
    rank: int,
    collected_at: str,
) -> HotItem | None:
    identifier = str(question_id or "").strip()
    clean_title = str(title or "").strip()
    clean_url = str(url or "").strip()
    score = parse_hot_score(str(heat_label or ""))
    if not identifier.isdigit() or not clean_title or score is None or score <= 0:
        return None
    expected = f"https://www.zhihu.com/question/{identifier}"
    if clean_url.startswith("/"):
        clean_url = "https://www.zhihu.com" + clean_url
    if clean_url != expected:
        clean_url = expected
    return HotItem(
        item_id=f"zhihu_hot_question_{identifier}",
        platform="zhihu_hot",
        title=clean_title,
        url=clean_url,
        rank=rank,
        heat=HeatMetrics(
            value=score,
            label=str(heat_label or "").strip(),
            metric_name="hot_score",
            metrics={"hot_score": score},
        ),
        summary=str(summary or "").strip(),
        publication_time=None,
        collected_at=collected_at,
        raw_payload={"question_id": identifier},
    )
```

`parse_api_hot_list` must:

1. Decode JSON object.
2. Require a nonempty `data` list.
3. Read `target.id`, `title_area.text`, `excerpt_area.text`, `metrics_area.text`, and `link.url`.
4. Assign ranks after invalid rows are removed.
5. Accept 1–50 valid items and reject an empty result.

`parse_html_hot_list` must:

1. Extract and JSON-decode `script#js-initialData`.
2. Read `initialState.topstory.hotList`.
3. If hydration data is absent or invalid, use a bounded `HTMLParser` for `data-za-detail-view-path-module="HotItem"` sections.
4. Feed both paths through `_hot_item`.
5. Reject an empty result.

Replace the Task 2 `collect_hot_list` stub:

```python
def collect_hot_list(self, collected_at: str) -> ProviderCapture:
    api = self._get(ZHIHU_HOT_API_URL)
    try:
        items = self.parse_api_hot_list(api.text, collected_at)
    except ProviderContractError:
        page = self._get(ZHIHU_HOT_PAGE_URL)
        items = self.parse_html_hot_list(page.text, collected_at)
        return ProviderCapture(
            page.text, ".html", items, metadata={"source": "html_fallback"}
        )
    return ProviderCapture(api.text, ".json", items, metadata={"source": "api"})
```

- [ ] **Step 5: Run provider and full tests**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py -q
uv run pytest -q
git diff --check
```

Expected: API, HTML, fallback and regression tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/heated_topics_v3/providers/zhihu_hot.py tests/providers/test_zhihu_hot.py tests/fixtures/zhihu_hot_api.json tests/fixtures/zhihu_hot_page.html
git commit -m "feat: collect real zhihu hot board"
```

---

### Task 4: Fetch Question Details and Up to Five Hot Answers

**Files:**
- Modify: `src/heated_topics_v3/providers/zhihu_hot.py`
- Modify: `tests/providers/test_zhihu_hot.py`
- Create: `tests/fixtures/zhihu_hot_question.json`
- Create: `tests/fixtures/zhihu_hot_answers.json`
- Create: `tests/fixtures/zhihu_hot_question_page.html`

**Interfaces:**
- Produces: `ZhihuHotProvider.fetch_detail(item, collected_at) -> ItemDetail` with full text and structured metadata.
- Produces: `_AnswerPayload` with cleaned answer text plus `as_metadata()`.
- Produces: `_QuestionPayload(question_text: str, question_stats: Mapping[str, int | str], answers: tuple[_AnswerPayload, ...], publication_time: str | None)`.
- Guarantees: at most 5 answers, sanitized author and metrics, no Cookie in metadata.

- [ ] **Step 1: Create exact question and answer fixtures**

Create `tests/fixtures/zhihu_hot_question.json`:

```json
{
  "id": 2064289475916560021,
  "title": "示例平台因垄断行为被处罚，会带来哪些影响？",
  "detail": "<p>监管机构依法完成调查并公布处罚决定，公开说明了案件事实、处罚依据、违法所得和整改要求。</p><p>此次处理将影响平台规则、商家经营和行业竞争，也可能改变消费者选择、价格形成和流量分配机制。</p>",
  "answer_count": 583,
  "follower_count": 1465,
  "visit_count": 1985997,
  "created": 1784950000,
  "updated_time": 1784980000
}
```

Create `tests/fixtures/zhihu_hot_answers.json`:

```json
{
  "data": [
    {
      "id": 2064295804840547334,
      "content": "<p>第一位作者分析了处罚依据、案件事实和可能产生的行业影响，并说明监管规则适用的基本边界。</p><p>回答进一步解释了平台流量分配和价格规则如何影响商家选择，也说明消费者可能获得的长期收益。</p><p>最后结合公开处罚信息给出了对后续整改方向、竞争格局以及平台治理机制的判断。</p>",
      "voteup_count": 1551,
      "comment_count": 407,
      "created_time": 1784975220,
      "updated_time": 1784975220,
      "author": {"name": "示例作者甲"},
      "url": "https://www.zhihu.com/question/2064289475916560021/answer/2064295804840547334"
    },
    {
      "id": 2064294236040717230,
      "content": "<p>第二位作者从市场结构、平台份额和交易条件出发分析问题，并区分企业规模与滥用行为。</p><p>回答说明了供应商议价能力、消费者选择范围以及其他竞争平台可能受到的具体影响。</p><p>作者认为长期效果取决于整改执行、持续监督和新的行业规则能否真正落地。</p>",
      "voteup_count": 702,
      "comment_count": 82,
      "created_time": 1784974860,
      "updated_time": 1784974860,
      "author": {"name": "示例作者乙"},
      "url": "https://www.zhihu.com/question/2064289475916560021/answer/2064294236040717230"
    }
  ],
  "paging": {"is_end": true}
}
```

Create `tests/fixtures/zhihu_hot_question_page.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <body>
    <main data-question-id="2064289475916560021">
      <h1>示例平台因垄断行为被处罚，会带来哪些影响？</h1>
      <div class="QuestionRichText">
        <p>监管机构依法完成调查并公布处罚决定，公开说明了案件事实、处罚依据、违法所得和整改要求。</p>
        <p>此次处理将影响平台规则、商家经营和行业竞争，也可能改变消费者选择、价格形成和流量分配机制。</p>
      </div>
      <button>关注者 1,465</button>
      <span>被浏览</span><strong>1,985,997</strong>
      <h4>583 个回答</h4>
      <article data-answer-id="2064295804840547334">
        <a class="author">示例作者甲</a>
        <div class="RichContent-inner">
          <p>第一位作者分析了处罚依据、案件事实和可能产生的行业影响，并说明监管规则适用的基本边界。</p>
          <p>回答进一步解释了平台流量分配和价格规则如何影响商家选择，也说明消费者可能获得的长期收益。</p>
          <p>最后结合公开处罚信息给出了对后续整改方向、竞争格局以及平台治理机制的判断。</p>
        </div>
        <a href="/question/2064289475916560021/answer/2064295804840547334">发布于2026-07-25 10:27</a>
        <button>赞同 1551</button><button>407 条评论</button>
        <button>收藏</button><span>276</span>
        <button>喜欢</button><span>27</span>
      </article>
    </main>
  </body>
</html>
```

- [ ] **Step 2: Write failing API, fallback, limit, and metadata tests**

Append:

```python
import json


def _hot_item():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider
    return ZhihuHotProvider.parse_api_hot_list(
        _fixture("zhihu_hot_api.json"), NOW
    )[0]


def test_question_api_builds_full_text_and_metadata():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/answers"):
            body = _fixture("zhihu_hot_answers.json")
        else:
            body = _fixture("zhihu_hot_question.json")
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )

    assert detail.content_status == "full_text"
    assert "问题描述" in detail.content
    assert "热门回答 1" in detail.content
    assert "热门回答 2" in detail.content
    assert detail.metadata["question"] == {
        "question_id": "2064289475916560021",
        "follower_count": 1465,
        "view_count": 1985997,
        "answer_count": 583,
    }
    assert detail.metadata["answers"][0]["author"] == "示例作者甲"
    assert detail.metadata["answers"][0]["voteup_count"] == 1551


def test_question_detail_caps_answers_at_five():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    answers = json.loads(_fixture("zhihu_hot_answers.json"))
    answers["data"] = answers["data"] * 4

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.dumps(answers, ensure_ascii=False)
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert len(detail.metadata["answers"]) == 5


def test_question_api_contract_change_falls_back_to_html():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            _fixture("zhihu_hot_question_page.html")
            if request.url.path.startswith("/question/")
            else "{}"
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success:html_fallback"
    assert len(detail.metadata["answers"]) == 1
    assert detail.metadata["answers"][0]["favorite_count"] == 276
    assert detail.metadata["answers"][0]["like_count"] == 27


def test_short_answer_is_skipped_but_question_can_still_qualify():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    answers = json.loads(_fixture("zhihu_hot_answers.json"))
    answers["data"][0]["content"] = "<p>太短。</p>"

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.dumps(answers, ensure_ascii=False)
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert all(answer["answer_id"] != "2064295804840547334"
               for answer in detail.metadata["answers"])


def test_question_without_answers_is_partial_if_description_qualifies():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            '{"data":[],"paging":{"is_end":true}}'
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "partial:no_answers"
    assert detail.metadata["answers"] == []


def test_detail_metadata_contains_no_cookie():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    cookie = "z_c0=private-cookie-value"
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            _fixture("zhihu_hot_answers.json")
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), cookie).fetch_detail(_hot_item(), NOW)
    assert cookie not in json.dumps(detail.metadata, ensure_ascii=False)
    assert cookie not in detail.content
```

- [ ] **Step 3: Run detail tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py -q
```

Expected: failures because `fetch_detail` does not parse question/answers or metadata.

- [ ] **Step 4: Implement question/answer API parsing and HTML fallback**

Add constants:

```python
ZHIHU_QUESTION_API_URL = (
    "https://www.zhihu.com/api/v4/questions/{question_id}"
    "?include=detail,answer_count,follower_count,visit_count,created,updated_time"
)
ZHIHU_ANSWERS_API_URL = (
    "https://www.zhihu.com/api/v4/questions/{question_id}/answers"
    "?include=data[*].content,voteup_count,comment_count,created_time,"
    "updated_time,author.name&limit=5&offset=0&platform=desktop&sort_by=default"
)
ZHIHU_QUESTION_PAGE_URL = "https://www.zhihu.com/question/{question_id}"
MAX_HOT_ANSWERS = 5
```

Add these imports:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from heated_topics_v3.content import validate_full_text
from heated_topics_v3.contracts import QualifiedArticle
```

Use frozen internal dataclasses:

```python
@dataclass(frozen=True)
class _AnswerPayload:
    answer_id: str
    author: str
    content: str
    voteup_count: int
    comment_count: int
    created_at: str | None
    updated_at: str | None
    url: str
    favorite_count: int | None = None
    like_count: int | None = None

    def as_metadata(self) -> dict[str, object]:
        return {
            "answer_id": self.answer_id,
            "author": self.author,
            "voteup_count": self.voteup_count,
            "comment_count": self.comment_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "url": self.url,
            "favorite_count": self.favorite_count,
            "like_count": self.like_count,
        }


@dataclass(frozen=True)
class _QuestionPayload:
    question_text: str
    question_stats: Mapping[str, int | str]
    answers: tuple[_AnswerPayload, ...]
    publication_time: str | None
```

Implement the shared conversion helpers:

```python
def _question_id(item: HotItem) -> str:
    value = str(item.raw_payload.get("question_id") or "").strip()
    if not value.isdigit():
        raise ProviderContractError("zhihu question id missing")
    return value


def _unix_iso(value: object) -> str | None:
    number = number_or_none(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()


def _clean_html_blocks(value: str) -> tuple[str, ...]:
    parser = _BlockTextParser()
    parser.feed(value)
    return tuple(part for part in parser.parts if part)


def _render_question_detail(payload: _QuestionPayload) -> str:
    sections = ["问题描述", payload.question_text]
    for index, answer in enumerate(payload.answers, 1):
        sections.extend(
            [
                f"热门回答 {index}",
                f"作者：{answer.author}",
                f"赞同：{answer.voteup_count}",
                f"评论：{answer.comment_count}",
                answer.content,
            ]
        )
    return "\n\n".join(section for section in sections if section.strip())
```

Implement `_BlockTextParser(HTMLParser)` with the same block-boundary behavior
as the existing Zhihu Daily body parser: flush text at `p`, `div`, `li`,
`blockquote`, headings and `br`; ignore `script`, `style`, `nav`, `footer`,
buttons and SVG; normalize whitespace; never retain tag names or attributes.

Implement `_parse_question_api` with this exact validation:

```python
def _parse_question_api(
    question_raw: str,
    answers_raw: str,
) -> _QuestionPayload:
    try:
        question = json.loads(question_raw)
        answers_envelope = json.loads(answers_raw)
    except (TypeError, ValueError) as error:
        raise ProviderContractError("zhihu question API returned invalid JSON") from error
    if not isinstance(question, dict) or not isinstance(answers_envelope, dict):
        raise ProviderContractError("zhihu question API envelope invalid")
    question_id = str(question.get("id") or "").strip()
    blocks = _clean_html_blocks(str(question.get("detail") or ""))
    if not question_id.isdigit() or not blocks:
        raise ProviderContractError("zhihu question API detail missing")
    rows = answers_envelope.get("data")
    if not isinstance(rows, list):
        raise ProviderContractError("zhihu answers API data missing")

    parsed_answers: list[_AnswerPayload] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        answer_id = str(row.get("id") or "").strip()
        content = "\n".join(_clean_html_blocks(str(row.get("content") or "")))
        if not answer_id.isdigit() or answer_id in seen:
            continue
        validation = validate_full_text(
            content, "", "", parser="zhihu_answer"
        )
        if validation.status != "accepted":
            continue
        seen.add(answer_id)
        author = row.get("author") if isinstance(row.get("author"), dict) else {}
        parsed_answers.append(
            _AnswerPayload(
                answer_id=answer_id,
                author=str(author.get("name") or "匿名用户").strip() or "匿名用户",
                content=content,
                voteup_count=number_or_none(row.get("voteup_count")) or 0,
                comment_count=number_or_none(row.get("comment_count")) or 0,
                created_at=_unix_iso(row.get("created_time")),
                updated_at=_unix_iso(row.get("updated_time")),
                url=str(row.get("url") or (
                    f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
                )),
            )
        )
        if len(parsed_answers) == MAX_HOT_ANSWERS:
            break

    return _QuestionPayload(
        question_text="\n".join(blocks),
        question_stats={
            "question_id": question_id,
            "follower_count": number_or_none(question.get("follower_count")) or 0,
            "view_count": number_or_none(question.get("visit_count")) or 0,
            "answer_count": number_or_none(question.get("answer_count")) or 0,
        },
        answers=tuple(parsed_answers),
        publication_time=_unix_iso(question.get("created")),
    )
```

Implement `_QuestionPageParser(HTMLParser)` for the fallback fixture and live
DOM with these exact state boundaries:

- Enter question text only inside `.QuestionRichText`.
- Enter one answer inside `article[data-answer-id]`.
- Enter answer text only inside `.RichContent-inner`.
- Read author from `.author`.
- Read answer URL and publish/edit labels from `/answer/` anchors.
- Parse follower, view, answer, vote, comment, favorite and like counts from
  their adjacent visible labels.
- Close and append an answer only when it has a numeric ID and accepted body.
- Stop appending after `MAX_HOT_ANSWERS`.

`_parse_question_html(raw, question_id)` feeds this parser, requires nonempty
question text, and returns `_QuestionPayload`; a missing question body raises
`ProviderContractError("zhihu question HTML detail missing")`.

Required answer metadata keys:

```python
{
    "answer_id": str,
    "author": str,
    "voteup_count": int,
    "comment_count": int,
    "created_at": str | None,
    "updated_at": str | None,
    "url": str,
    "favorite_count": int | None,
    "like_count": int | None,
}
```

`favorite_count` and `like_count` are populated by the HTML fallback when the
page exposes them; API results use `None` when those fields are absent. Do not
store answer HTML or Cookie in metadata. The cleaned answer text belongs only
in `ItemDetail.content`.

`fetch_detail` flow:

```python
def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
    question_id = _question_id(item)
    try:
        question = self._get(ZHIHU_QUESTION_API_URL.format(question_id=question_id))
        answers = self._get(ZHIHU_ANSWERS_API_URL.format(question_id=question_id))
        payload = _parse_question_api(question.text, answers.text)
        fetch_status = "success" if payload.answers else "partial:no_answers"
    except ProviderContractError:
        page = self._get(ZHIHU_QUESTION_PAGE_URL.format(question_id=question_id))
        payload = _parse_question_html(page.text, question_id)
        fetch_status = (
            "success:html_fallback"
            if payload.answers
            else "partial:html_fallback:no_answers"
        )

    content = _render_question_detail(payload)
    validation = validate_full_text(
        content, item.title, item.summary, parser="zhihu_question"
    )
    if validation.status != "accepted":
        return ItemDetail(
            item.item_id, "", "rejected", payload.publication_time,
            collected_at, item.url, "rejected:" + ",".join(validation.reasons),
        )
    return ItemDetail(
        item_id=item.item_id,
        content=content,
        content_status="full_text",
        publication_time=payload.publication_time,
        collected_at=collected_at,
        source_url=item.url,
        fetch_status=fetch_status,
        metadata={
            "question": dict(payload.question_stats),
            "answers": [answer.as_metadata() for answer in payload.answers],
        },
    )
```

Authentication exceptions must propagate; only schema/parse errors trigger HTML fallback.

- [ ] **Step 5: Add deterministic provider ranking**

Implement:

```python
def rank_articles(
    self, articles: Sequence[QualifiedArticle]
) -> tuple[QualifiedArticle, ...]:
    ordered = list(rank_platform_articles(tuple(articles), self.weights))
    ordered.sort(key=lambda article: article.hot_item.item_id)
    ordered.sort(
        key=lambda article: float(
            article.detail.metadata.get("question", {}).get("view_count", 0)
        ),
        reverse=True,
    )
    ordered.sort(
        key=lambda article: article.hot_item.rank or 10**9
    )
    ordered.sort(
        key=lambda article: float(article.hot_item.heat.value or 0),
        reverse=True,
    )
    return tuple(ordered)
```

Import `rank_platform_articles` only if needed for score calculation; ensure final primary key remains `hot_score` descending.

- [ ] **Step 6: Run provider, storage, and full tests**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py tests/test_storage.py tests/test_news_collection.py -q
uv run pytest -q
git diff --check
```

Expected: detail API, HTML fallback, metadata, limit and full regression tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/heated_topics_v3/providers/zhihu_hot.py tests/providers/test_zhihu_hot.py tests/fixtures/zhihu_hot_question.json tests/fixtures/zhihu_hot_answers.json tests/fixtures/zhihu_hot_question_page.html
git commit -m "feat: collect zhihu question hot answers"
```

---

### Task 5: Extend Zhihu Daily With Top Stories

**Files:**
- Modify: `src/heated_topics_v3/providers/zhihu_daily.py`
- Modify: `tests/fixtures/zhihu_daily_latest.json`
- Modify: `tests/providers/test_zhihu_daily.py`

**Interfaces:**
- Preserves: `ZhihuDailyProvider.parse_latest(raw, collected_at)`.
- Adds: `raw_payload["recommendation_section"] in {"latest", "top"}`.
- Adds: `raw_payload["recommendation_sections"]` when a story appears in both sections.
- Guarantees: top stories sort before latest stories; archive behavior stays unchanged.

- [ ] **Step 1: Extend the latest fixture and write failing tests**

Add to `tests/fixtures/zhihu_daily_latest.json`:

```json
"top_stories": [
  {
    "id": 1002,
    "title": "置顶推荐：新的科学发现意味着什么",
    "hint": "知乎日报 · 置顶",
    "type": 0,
    "url": "https://daily.zhihu.com/story/1002",
    "image": "https://pic.example.test/1002.jpg"
  },
  {
    "id": 1001,
    "title": "人工智能工具如何改变内容创作",
    "hint": "知乎日报 · 8 分钟阅读",
    "type": 0,
    "url": "https://daily.zhihu.com/story/1001",
    "image": "https://pic.example.test/1001.jpg"
  }
]
```

Keep the existing `stories` list with story `1001` so the fixture exercises deduplication.

Add:

```python
def test_latest_includes_top_stories_and_deduplicates_story_ids():
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    items = ZhihuDailyProvider.parse_latest(
        _fixture("zhihu_daily_latest.json"), NOW
    )
    assert [item.item_id for item in items] == [
        "zhihu_daily_1002",
        "zhihu_daily_1001",
    ]
    duplicate = items[1]
    assert duplicate.raw_payload["recommendation_section"] == "top"
    assert duplicate.raw_payload["recommendation_sections"] == ("top", "latest")


def test_rank_articles_places_top_before_latest():
    from dataclasses import replace
    from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

    provider = ZhihuDailyProvider(_client(lambda request: httpx.Response(404)))
    top = _archive_article("20260725", 1002, 2)
    top = replace(
        top,
        hot_item=replace(
            top.hot_item,
            raw_payload={
                **top.hot_item.raw_payload,
                "recommendation_section": "top",
            },
        ),
    )
    latest = _archive_article("20260725", 1001, 1)
    latest = replace(
        latest,
        hot_item=replace(
            latest.hot_item,
            raw_payload={
                **latest.hot_item.raw_payload,
                "recommendation_section": "latest",
            },
        ),
    )
    assert provider.rank_articles([latest, top])[0].hot_item.item_id == top.hot_item.item_id
```

- [ ] **Step 2: Run daily tests and verify RED**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_daily.py -q
```

Expected: missing top story and ordering assertions fail.

- [ ] **Step 3: Implement section parsing, deduplication, and ranking**

Refactor `parse_latest` to parse `top_stories` first, then `stories`. Use a dict keyed by integer story ID. For duplicates, retain the `top` item and set:

```python
raw_payload={
    **existing.raw_payload,
    "recommendation_section": "top",
    "recommendation_sections": ("top", "latest"),
}
```

For nonduplicates:

```python
"recommendation_section": section
"recommendation_sections": (section,)
```

`rank_articles` primary key becomes:

```python
section_priority = (
    0 if article.hot_item.raw_payload.get("recommendation_section") == "top" else 1
)
```

Then preserve recommendation date descending, within-section rank ascending, publication time descending, and stable story ID.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_daily.py -q
uv run pytest -q
git diff --check
```

Expected: top/latest tests and all archive regressions pass.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/providers/zhihu_daily.py tests/providers/test_zhihu_daily.py tests/fixtures/zhihu_daily_latest.json
git commit -m "feat: collect zhihu daily top stories"
```

---

### Task 6: Add No-Search Discovery and 48-Hour Stale Snapshot Fallback

**Files:**
- Modify: `src/heated_topics_v3/discovery.py`
- Modify: `tests/test_discovery.py`

**Interfaces:**
- Consumes: optional `provider.supports_search: bool`.
- Produces: `_supports_search(provider: NewsProvider) -> bool`.
- Guarantees: `supports_search=False` never calls `provider.search`.
- Guarantees: matched current items are preferred; otherwise a valid active snapshot is returned with `snapshot_date` and `is_stale=True`.

- [ ] **Step 1: Write failing no-search and stale snapshot tests**

Add a fake:

```python
class NoSearchProvider(FakeProvider):
    supports_search = False

    def __init__(self):
        super().__init__(
            "zhihu_hot",
            weights={"hot_score": 1.0},
            absolute_floors={"hot_score": 1.0},
        )

    def search(self, keyword, page, page_size, collected_at):
        raise AssertionError("zhihu hot must not call search")
```

Add tests:

```python
def test_no_search_provider_returns_current_matches_without_search(tmp_path):
    repository = FileRepository(tmp_path)
    provider = NoSearchProvider()
    article = _build_article(
        _make_hot_item(
            platform="zhihu_hot",
            item_id="zhihu_hot_question_1",
            rank=1,
            title=f"{KEYWORD} 热榜问题",
            metrics={"hot_score": 1000},
        )
    )
    repository.save_eligible(BUSINESS_DATE, "zhihu_hot", (article,))

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )
    assert [row.hot_item.item_id for row in result] == ["zhihu_hot_question_1"]


def test_no_search_provider_uses_active_snapshot_within_48_hours(tmp_path):
    repository = FileRepository(tmp_path)
    provider = NoSearchProvider()
    previous_date = "2026-07-22"
    article = _build_article(
        _make_hot_item(
            platform="zhihu_hot",
            item_id="zhihu_hot_question_old",
            rank=2,
            title=f"{KEYWORD} 昨日热榜问题",
            metrics={"hot_score": 900},
        )
    )
    repository.save_eligible(previous_date, "zhihu_hot", (article,))
    repository.publish_active_snapshot("zhihu_hot", previous_date)

    result = discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    )
    assert result[0].hot_item.raw_payload["is_stale"] is True
    assert result[0].hot_item.raw_payload["snapshot_date"] == previous_date


def test_no_search_provider_rejects_snapshot_older_than_48_hours(tmp_path):
    repository = FileRepository(tmp_path)
    provider = NoSearchProvider()
    old_date = "2026-07-20"
    article = _build_article(
        _make_hot_item(
            platform="zhihu_hot",
            item_id="zhihu_hot_question_too_old",
            rank=1,
            title=f"{KEYWORD} 过期热榜问题",
            metrics={"hot_score": 800},
        )
    )
    repository.save_eligible(old_date, "zhihu_hot", (article,))
    repository.publish_active_snapshot("zhihu_hot", old_date)

    assert discover_platform_articles(
        PROFILE, BUSINESS_DATE, COLLECTED_AT, repository, provider
    ) == ()
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
uv run pytest tests/test_discovery.py -q
```

Expected: `provider.search` assertion fires or stale snapshot is not returned.

- [ ] **Step 3: Implement explicit no-search branching**

Add:

```python
def _supports_search(provider: NewsProvider) -> bool:
    return bool(getattr(provider, "supports_search", True))
```

In `discover_platform_articles`, immediately after the `len(matched) >= MIN_RESULTS` branch:

```python
if not _supports_search(provider):
    if matched:
        return _rank_cached_only(matched, provider)
    snapshot = repository.resolve_eligible_snapshot(
        provider.platform, collected_at, max_age_hours=48
    )
    if snapshot is None:
        return ()
    snapshot_date, snapshot_articles = snapshot
    snapshot_matched = _match_articles(profile, snapshot_articles)
    return _rank_snapshot(
        snapshot_matched,
        provider,
        snapshot_date=snapshot_date,
    )
```

Do not create a search cache record for `supports_search=False`; there was no search request.

- [ ] **Step 4: Run discovery and full regressions**

Run:

```powershell
uv run pytest tests/test_discovery.py tests/test_news_recommendation.py -q
uv run pytest -q
git diff --check
```

Expected: no-search tests pass; existing Sina/The Paper/NetEase/Baidu/Daily search behavior is unchanged.

- [ ] **Step 5: Commit**

```powershell
git add src/heated_topics_v3/discovery.py tests/test_discovery.py
git commit -m "feat: support cached no-search providers"
```

---

### Task 7: Register `zhihu_hot`, Load Cookie, and Add Auth CLI

**Files:**
- Modify: `src/heated_topics_v3/providers/common.py`
- Modify: `src/heated_topics_v3/providers/__init__.py`
- Modify: `src/heated_topics_v3/collection.py`
- Modify: `src/heated_topics_v3/recommendation.py`
- Modify: `src/heated_topics_v3/cli.py`
- Modify: `src/heated_topics_v3/__init__.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `tests/test_news_collection.py`
- Modify: `tests/test_news_recommendation.py`
- Modify: `tests/test_news_cli.py`

**Interfaces:**
- Produces: `heated-topics check-zhihu-auth`.
- Produces: `_load_zhihu_cookie() -> str`.
- Updates: `NEWS_PLATFORMS` and `NEWS_DISPLAY_ORDER` to include `zhihu_hot` before `zhihu_daily`.
- Guarantees: missing Cookie fails only `zhihu_hot`, not construction of the provider mapping.

- [ ] **Step 1: Write failing registration and CLI tests**

Update platform assertions:

```python
assert NEWS_PLATFORMS == (
    "sina_news",
    "thepaper",
    "netease_news",
    "baidu_hot",
    "zhihu_hot",
    "zhihu_daily",
)
```

Use the same order for `NEWS_DISPLAY_ORDER`.

Add to `tests/test_news_cli.py`:

```python
def test_news_provider_mapping_accepts_missing_zhihu_cookie(monkeypatch):
    from heated_topics_v3 import cli

    monkeypatch.delenv("ZHIHU_COOKIE", raising=False)
    with cli._client() as client:
        providers = cli._news_providers(client)

    assert providers["zhihu_hot"].cookie == ""
    assert "zhihu_daily" in providers


def test_check_zhihu_auth_emits_sanitized_valid_status(monkeypatch, capsys):
    from heated_topics_v3 import cli

    monkeypatch.setenv("ZHIHU_COOKIE", "z_c0=private-cookie-value")
    monkeypatch.setattr(
        "heated_topics_v3.providers.zhihu_hot.ZhihuHotProvider.check_auth",
        lambda self: "valid",
    )

    assert cli.main(["check-zhihu-auth"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "valid"
    assert payload["command"] == "check-zhihu-auth"
    assert datetime.fromisoformat(payload["checked_at"]).tzinfo is not None
    assert "private-cookie-value" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("health", "exit_code"),
    [("missing", 1), ("expired", 1), ("blocked", 1), ("contract_changed", 1)],
)
def test_check_zhihu_auth_failure_exit_codes(monkeypatch, capsys, health, exit_code):
    from heated_topics_v3 import cli

    monkeypatch.setenv("ZHIHU_COOKIE", "z_c0=local")
    monkeypatch.setattr(
        "heated_topics_v3.providers.zhihu_hot.ZhihuHotProvider.check_auth",
        lambda self: health,
    )
    assert cli.main(["check-zhihu-auth"]) == exit_code
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == health
    assert payload["command"] == "check-zhihu-auth"
    assert datetime.fromisoformat(payload["checked_at"]).tzinfo is not None


def test_missing_cookie_only_fails_zhihu_hot_collection(tmp_path):
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    providers = _build_providers()
    providers["zhihu_hot"] = ZhihuHotProvider(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, request=request)
            )
        ),
        "",
    )

    snapshot = collect_news_daily(NOW, FileRepository(tmp_path), providers)
    statuses = {row.platform: row for row in snapshot.platform_statuses}
    assert statuses["zhihu_hot"].status == "failed"
    assert statuses["zhihu_hot"].error == "auth_missing"
    assert statuses["zhihu_daily"].status == "success"
```

Add `import httpx` to `tests/test_news_collection.py`; keep this test in that file so it can use `_build_providers`, `NOW`, and `FileRepository`.

- [ ] **Step 2: Run registration tests and verify RED**

Run:

```powershell
uv run pytest tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py -q
```

Expected: platform order and missing command failures.

- [ ] **Step 3: Register the Provider and load `.env` safely**

Update `NEWS_PLATFORMS` and `NEWS_DISPLAY_ORDER` with `zhihu_hot` immediately before `zhihu_daily`.

In `collection.py`, import the three authentication exceptions and
`ProviderContractError`, then add:

```python
def _news_error_code(error: Exception) -> str:
    if isinstance(error, MissingCredentialError):
        return "auth_missing"
    if isinstance(error, AuthenticationExpiredError):
        return "auth_expired"
    if isinstance(error, AuthenticationBlockedError):
        return "auth_blocked"
    if isinstance(error, ProviderContractError):
        return "contract_changed"
    return type(error).__name__
```

Use `error=_news_error_code(error)` in the failed `PlatformCollectionStatus`
created by `collect_news_daily`. Do not put `str(error)` in persisted status.

Export `ZhihuHotProvider` from `providers/__init__.py` and the public package only if the package currently exports other Provider classes.

In `cli.py`, import:

```python
import os
from dotenv import load_dotenv
from .providers.zhihu_hot import ZhihuHotProvider
```

Add:

```python
def _load_zhihu_cookie() -> str:
    load_dotenv()
    return os.getenv("ZHIHU_COOKIE", "").strip()
```

Update `_news_providers`:

```python
"zhihu_hot": ZhihuHotProvider(client, _load_zhihu_cookie()),
"zhihu_daily": ZhihuDailyProvider(client),
```

The constructor must not raise when the Cookie is empty.

- [ ] **Step 4: Add the health command and deterministic output**

In `_parser()`:

```python
commands.add_parser("check-zhihu-auth")
```

Add:

```python
def _check_zhihu_auth() -> tuple[int, dict[str, object]]:
    with _client() as client:
        status = ZhihuHotProvider(client, _load_zhihu_cookie()).check_auth()
    return (0 if status == "valid" else 1), {
        "status": status,
        "command": "check-zhihu-auth",
        "checked_at": datetime.now(SHANGHAI).isoformat(),
    }
```

Dispatch this branch explicitly before the generic `generate-news` branch:

```python
elif arguments.command == "check-zhihu-auth":
    exit_code, payload = _check_zhihu_auth()
```

Never include exception text or response body in this command.

- [ ] **Step 5: Document the local Cookie workflow**

Append to `.env.example`:

```text
# Zhihu real hot list (required only for zhihu_hot).
# Copy the complete Cookie request header from your own signed-in zhihu.com
# session. Keep it local. Never commit the value.
ZHIHU_COOKIE=
```

Add to `README.md`:

````markdown
### Zhihu sources

`zhihu_daily` is anonymous. `zhihu_hot` needs a locally maintained
`ZHIHU_COOKIE` in `.env`.

Check it without writing the Cookie or response body:

```powershell
uv run heated-topics check-zhihu-auth
```

Valid output:

```json
{"status":"valid","command":"check-zhihu-auth","checked_at":"2026-07-25T20:00:00+08:00"}
```

If the status is `missing` or `expired`, replace only the local `.env` value
and rerun the check. `collect-news` isolates this failure from every other
platform.
````

- [ ] **Step 6: Run CLI, workflow, full, and secret checks**

Run:

```powershell
uv run pytest tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py -q
uv run pytest -q
uv run python -m compileall -q src tests
git diff --check
rg -n "private-cookie-value|z_c0=local" src README.md .env.example
```

Expected: tests pass; compile and diff checks exit 0; the final `rg` exits 1
with no matches in production source or user documentation. The same values
may appear only inside tests and this implementation plan.

- [ ] **Step 7: Commit**

```powershell
git add .env.example README.md src/heated_topics_v3/__init__.py src/heated_topics_v3/cli.py src/heated_topics_v3/collection.py src/heated_topics_v3/providers/__init__.py src/heated_topics_v3/providers/common.py src/heated_topics_v3/providers/zhihu_hot.py src/heated_topics_v3/recommendation.py tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py
git commit -m "feat: register zhihu dual sources"
```

Do not stage `.env` or any real response artifact.

---

### Task 8: Run Real Smoke Verification and Record Evidence

**Files:**
- Modify: `tools/validate_news_smoke.py`
- Modify: `tests/test_news_smoke_validator.py`
- Create: `docs/specs/zhihu-dual-source-implementation-report.md`

**Interfaces:**
- Produces: smoke validator checks for `zhihu_hot` item count, question metadata, answer limit, `zhihu_daily` content, ordering and secrets.
- Produces: an evidence-based implementation report without real Cookie or article/answer bodies.

- [ ] **Step 1: Write failing validator tests**

Add fixtures in `tests/test_news_smoke_validator.py` using temporary JSON files:

```python
def test_smoke_validator_rejects_more_than_five_zhihu_answers(tmp_path: Path):
    details = tmp_path / "daily_hot_lists" / "2026-07-25" / "details"
    details.mkdir(parents=True)
    (details / "zhihu_hot_zhihu_hot_question_1.json").write_text(
        json.dumps({
            "item_id": "zhihu_hot_question_1",
            "content": "合格问题正文。",
            "content_status": "full_text",
            "publication_time": None,
            "collected_at": "2026-07-25T12:00:00+08:00",
            "source_url": "https://www.zhihu.com/question/1",
            "fetch_status": "success",
            "metadata": {
                "question": {"question_id": "1", "view_count": 100},
                "answers": [
                    {
                        "answer_id": str(index),
                        "url": f"https://www.zhihu.com/question/1/answer/{index}"
                    }
                    for index in range(6)
                ],
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert any(
        violation.startswith("zhihu-answer-limit:")
        for violation in json.loads(result.stdout)["violations"]
    )


def test_smoke_validator_accepts_ranked_zhihu_hot_and_daily(tmp_path: Path):
    eligible = tmp_path / "daily_hot_lists" / "2026-07-25" / "eligible"
    details = tmp_path / "daily_hot_lists" / "2026-07-25" / "details"
    eligible.mkdir(parents=True)
    details.mkdir(parents=True)
    hot_detail = {
        "item_id": "zhihu_hot_question_1",
        "content": "第一段完整问题内容。\n\n第二段完整热门回答内容。",
        "content_status": "full_text",
        "publication_time": None,
        "collected_at": "2026-07-25T12:00:00+08:00",
        "source_url": "https://www.zhihu.com/question/1",
        "fetch_status": "success",
        "metadata": {
            "question": {"question_id": "1", "view_count": 100},
            "answers": [{
                "answer_id": "11",
                "url": "https://www.zhihu.com/question/1/answer/11"
            }],
        },
    }
    hot_article = {
        "hot_item": {
            "item_id": "zhihu_hot_question_1",
            "platform": "zhihu_hot",
            "title": "示例热榜问题",
            "url": "https://www.zhihu.com/question/1",
            "rank": 1,
            "heat": {
                "value": 1000,
                "label": "1000 热度",
                "metric_name": "hot_score",
                "metrics": {"hot_score": 1000},
            },
            "summary": "摘要",
            "publication_time": None,
            "collected_at": "2026-07-25T12:00:00+08:00",
            "raw_payload": {"question_id": "1"},
        },
        "detail": hot_detail,
        "heat_evidence": {
            "source_kind": "official_hot_board",
            "platform_rank": 1,
            "native_hot_value": 1000,
            "metrics": {"hot_score": 1000},
            "threshold_metrics": {"hot_score": 1},
            "qualified_by": ["official_hot_board"],
        },
        "content_validation": {
            "status": "accepted",
            "parser": "fixture",
            "character_count": 100,
            "paragraph_count": 2,
            "reasons": [],
        },
        "platform_heat_score": 1.0,
    }
    daily_article = json.loads(json.dumps(hot_article))
    daily_article["hot_item"].update({
        "item_id": "zhihu_daily_2",
        "platform": "zhihu_daily",
        "url": "https://daily.zhihu.com/story/2",
        "heat": {"value": None, "label": "", "metric_name": "rank", "metrics": {}},
        "raw_payload": {
            "story_id": 2,
            "recommendation_section": "latest",
            "recommendation_sections": ["latest"],
        },
    })
    daily_article["detail"].update({
        "item_id": "zhihu_daily_2",
        "source_url": "https://daily.zhihu.com/story/2",
        "metadata": {},
    })
    daily_article["heat_evidence"].update({
        "native_hot_value": None,
        "metrics": {},
        "threshold_metrics": {},
    })
    (eligible / "zhihu_hot.json").write_text(
        json.dumps([hot_article], ensure_ascii=False), encoding="utf-8"
    )
    (eligible / "zhihu_daily.json").write_text(
        json.dumps([daily_article], ensure_ascii=False), encoding="utf-8"
    )
    (details / "zhihu_hot_zhihu_hot_question_1.json").write_text(
        json.dumps(hot_detail, ensure_ascii=False), encoding="utf-8"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_smoke_validator_rejects_cookie_shaped_content(tmp_path: Path):
    path = tmp_path / "daily_hot_lists" / "2026-07-25" / "eligible" / "zhihu_hot.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[{"Cookie":"z_c0=123456789abcdef"}]',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert any(
        violation.startswith("credential:")
        for violation in json.loads(result.stdout)["violations"]
    )
```

These tests use the existing `_run` subprocess helper and only synthetic bodies.

- [ ] **Step 2: Run validator tests and verify RED**

Run:

```powershell
uv run pytest tests/test_news_smoke_validator.py -q
```

Expected: answer limit or dual-source assertions fail because the validator does not inspect detail metadata yet.

- [ ] **Step 3: Extend the validator**

For each `details/zhihu_hot_*.json` sidecar:

```python
metadata = dict(payload.get("metadata") or {})
question = dict(metadata.get("question") or {})
answers = list(metadata.get("answers") or [])
if not question.get("question_id"):
    violations.append(f"zhihu-question:{path}")
if len(answers) > 5:
    violations.append(f"zhihu-answer-limit:{path}")
for answer in answers:
    if not answer.get("answer_id") or not answer.get("url"):
        violations.append(f"zhihu-answer:{path}")
```

For `eligible/zhihu_hot.json`, assert every record has:

```text
hot_item.rank > 0
hot_item.heat.metrics.hot_score > 0
hot_item.raw_payload.question_id
detail.content_status == "full_text"
```

For `eligible/zhihu_daily.json`, assert every record has:

```text
detail.content_status == "full_text"
hot_item.raw_payload.recommendation_section in {"top", "latest"} or
hot_item.raw_payload.official_recommendation is true for archive results
```

Keep the existing `SECRET` scan and rejected/eligible overlap check.

- [ ] **Step 4: Run isolated real collection**

Confirm the environment key exists without printing its value:

```powershell
uv run python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('configured' if os.getenv('ZHIHU_COOKIE','').strip() else 'missing')"
uv run heated-topics check-zhihu-auth
```

Expected:

```json
{"status":"valid","command":"check-zhihu-auth","checked_at":"2026-07-25T20:00:00+08:00"}
```

If it reports `missing` or `expired`, stop the real smoke portion and ask the user to replace the local `.env` value. Do not request the Cookie in chat.

Create a disposable root outside the repository:

```powershell
$zhihuSmokeRoot = Join-Path $env:TEMP 'heatedtopics-zhihu-smoke-20260725'
New-Item -ItemType Directory -Force -Path $zhihuSmokeRoot | Out-Null
uv run heated-topics collect-news --data-root $zhihuSmokeRoot
uv run python tools/validate_news_smoke.py $zhihuSmokeRoot
```

Expected:

- `zhihu_hot` status is `success` or `partial`, with 1–50 normalized items and normally about 30.
- At least one `zhihu_hot` eligible detail contains question metadata and no more than 5 answer metadata records.
- `zhihu_daily` has at least one normalized item and at least one eligible full-text item.
- Validator returns `{"status":"success","violations":[]}`.

- [ ] **Step 5: Exercise user matching for both platforms**

Read only titles and IDs from the smoke JSON; do not print bodies. Create two ignored profiles under the smoke root:

```powershell
uv run python -c "import json,sys; from pathlib import Path; root=Path(sys.argv[1]); day=next((root/'daily_hot_lists').iterdir()).name; hot=json.loads((root/'daily_hot_lists'/day/'eligible'/'zhihu_hot.json').read_text('utf-8')); daily=json.loads((root/'daily_hot_lists'/day/'eligible'/'zhihu_daily.json').read_text('utf-8')); print(hot[0]['hot_item']['title']); print(daily[0]['hot_item']['title'])" $zhihuSmokeRoot
```

Use a distinctive NFKC-normalized substring from each printed title as `primary_keyword`, then run:

```powershell
uv run heated-topics generate-news --data-root $zhihuSmokeRoot --profile $zhihuSmokeRoot\zhihu-hot-profile.json
uv run heated-topics generate-news --data-root $zhihuSmokeRoot --profile $zhihuSmokeRoot\zhihu-daily-profile.json
uv run python tools/validate_news_smoke.py $zhihuSmokeRoot
```

Inspect `result.json` programmatically and record only:

```text
platform
recommendation_count
is_stale
content_status
answer_metadata_count
elapsed_seconds
```

Do not copy real bodies into the report.

- [ ] **Step 6: Verify Cookie isolation**

Run:

```powershell
uv run python -c "import os,sys; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(); secret=os.getenv('ZHIHU_COOKIE',''); root=Path(sys.argv[1]); hits=[] if not secret else [str(p) for p in root.rglob('*') if p.is_file() and secret.encode() in p.read_bytes()]; print({'cookie_leaks':hits}); raise SystemExit(1 if hits else 0)" $zhihuSmokeRoot
rg -n -i "authorization|cookie|z_c0|session|token" $zhihuSmokeRoot
```

Expected: exact-secret scan exits 0 with an empty list. The generic `rg` may find fixed metadata field names only if tests intentionally use them; it must not find a credential value.

- [ ] **Step 7: Write the implementation report**

Create `docs/specs/zhihu-dual-source-implementation-report.md` with:

```markdown
# Zhihu Dual Source Implementation Report

## Scope and commit history

## Automated verification

## Real `zhihu_hot` verification

- Auth health status
- Board source used: API or HTML fallback
- Normalized, eligible, and rejected counts
- Detail success count
- Observed answer count range, capped at 5
- Main rejection reason codes

## Real `zhihu_daily` verification

- Latest count
- Top story count
- Eligible and rejected counts
- Archive discovery result

## User matching verification

- Per-platform recommendation counts
- Cache/stale behavior

## Credential isolation

- Exact-secret scan result
- Generic secret-pattern scan result

## Known limitations

- Cookie lifetime is controlled by Zhihu and cannot be guaranteed indefinitely.
- Replacing `ZHIHU_COOKIE` restores operation without a code change.
- API and HTML contract changes are reported explicitly.
```

Use measured counts and fixed status codes only. Do not paste real titles, descriptions, answers, Cookie values, response headers or complete API bodies.

- [ ] **Step 8: Run final verification**

Run:

```powershell
uv run pytest tests/providers/test_zhihu_hot.py tests/providers/test_zhihu_daily.py tests/test_discovery.py tests/test_news_collection.py tests/test_news_recommendation.py tests/test_news_cli.py tests/test_news_smoke_validator.py -q
uv run pytest -q
uv run python -m compileall -q src tests
uv run python tools/validate_news_smoke.py $zhihuSmokeRoot
git diff --check
git status --short
```

Expected:

- Focused and full test suites pass.
- Compile, validator, and diff checks exit 0.
- Git status lists only the intentional validator, tests and implementation report before commit.
- The disposable smoke root remains outside Git.

- [ ] **Step 9: Commit**

```powershell
git add tools/validate_news_smoke.py tests/test_news_smoke_validator.py docs/specs/zhihu-dual-source-implementation-report.md
git commit -m "docs: verify zhihu dual sources"
```

---

## Final Acceptance Checklist

- [ ] `ZHIHU_COOKIE` is loaded only from local environment state.
- [ ] `check-zhihu-auth` distinguishes `valid`, `missing`, `expired`, `blocked`, and `contract_changed`.
- [ ] API `401`/`403` and sign-in redirects never fall back as if they were schema changes.
- [ ] API schema changes can use the HTML hot-board fallback.
- [ ] Real `zhihu_hot` yields 1–50 normalized records, normally about 30.
- [ ] Every eligible hot item has positive rank, positive `hot_score`, question ID, URL and full text.
- [ ] Question details contain sanitized question metrics and at most 5 answer metadata records.
- [ ] `zhihu_hot` never calls ordinary keyword search.
- [ ] A valid active `zhihu_hot` snapshot may be reused for at most 48 hours and is marked stale.
- [ ] `zhihu_daily` collects both `stories` and `top_stories` anonymously.
- [ ] Duplicate Daily stories retain top identity and deterministic ordering.
- [ ] Existing seven-day Daily archive, 60-candidate and 20-result limits remain intact.
- [ ] A missing or expired Cookie fails only `zhihu_hot`.
- [ ] Cookie and session values do not appear in source, docs, fixtures, logs, cache or smoke output.
- [ ] `uv run pytest -q`, `compileall`, smoke validation and `git diff --check` pass.
