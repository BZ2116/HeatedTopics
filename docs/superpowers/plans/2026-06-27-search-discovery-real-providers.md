# Search Discovery Real Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `MockProvider`-only search in `src/search_discovery/` with real HTTP-based providers (GitHub, Bocha AI, Aliyun Bailian, Baidu Qianfan), preserving mock as fallback only for missing-key case.

**Architecture:** A `BaseHTTPSearchProvider` class encapsulates HTTP, retry, rate-limiting, and error normalization. Four concrete subclasses implement the per-source request/response specifics. CLI assembles the registry via `from_env()`; missing keys transparently fall back to `MockProvider(rows=[])` plus a `mock_unavailable` placeholder row.

**Tech Stack:** Python 3.10+, `httpx` (HTTP client with `MockTransport` for tests), `python-dotenv` (`.env` loading). Existing `pyproject.toml` uses `uv` for dependency management.

---

## File Structure

**New files:**
- `src/search_discovery/base_provider.py` — `BaseHTTPSearchProvider`, `TokenBucket`, error helpers
- `src/search_discovery/providers_github.py` — `GitHubSearchProvider`
- `src/search_discovery/providers_bocha.py` — `BochaSearchProvider`
- `src/search_discovery/providers_bailian.py` — `BailianWebSearchProvider`
- `src/search_discovery/providers_qianfan.py` — `QianfanSearchProvider`
- `tests/search_discovery/test_base_provider.py` — TokenBucket + retry/rate-limit tests
- `tests/search_discovery/test_providers_github.py`
- `tests/search_discovery/test_providers_bocha.py`
- `tests/search_discovery/test_providers_bailian.py`
- `tests/search_discovery/test_providers_qianfan.py`
- `tests/search_discovery/test_cli_fallback.py` — CLI fallback injection tests
- `.env.example` — template of required env vars
- `docs/superpowers/integrations/github-quickstart.md`
- `docs/superpowers/integrations/bocha-quickstart.md`
- `docs/superpowers/integrations/bailian-quickstart.md`
- `docs/superpowers/integrations/qianfan-quickstart.md`

**Modified files:**
- `pyproject.toml` — add `httpx`, `python-dotenv` to `dependencies`
- `.gitignore` — append `.env`
- `src/search_discovery/providers.py` — pass `fetch_status`/`error_type` through `normalize_provider_rows`; add `make_unavailable_row()` helper
- `src/search_discovery/cli.py` — replace `_default_mock_registry()` with `_build_registry()` that calls `from_env()` and emits fallback placeholders; load `.env` at startup

**Files that stay untouched:**
- `src/search_discovery/types.py`, `keywords.py`, `config.py`, `discovery.py`, `ranking.py`, `enrich.py`, `render.py`, `io.py`
- All existing tests except where noted below (existing `test_cli.py` may need fixture refresh)

---

## Task 1: Add dependencies and `.env` skeleton

**Files:**
- Modify: `pyproject.toml:6-9`
- Modify: `.gitignore`
- Create: `.env.example`

- [ ] **Step 1: Add `httpx` and `python-dotenv` to `pyproject.toml`**

Edit `pyproject.toml` so the `dependencies` block reads:

```toml
dependencies = [
    "playwright>=1.59.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0",
]
```

- [ ] **Step 2: Update the lock file**

Run: `uv lock`
Expected: lock file regenerated, no errors. If `uv` is unavailable, run `pip install httpx>=0.27.0 python-dotenv>=1.0` instead and skip lock update.

- [ ] **Step 3: Add `.env` to `.gitignore`**

Append to `.gitignore`:

```
# Local secrets
.env
```

- [ ] **Step 4: Create `.env.example`**

Write `.env.example` at the repo root:

```bash
# GitHub Search API (optional; without token: 60 req/h, with token: 5000 req/h)
# Create at: https://github.com/settings/tokens (no scopes required for /search)
GITHUB_TOKEN=

# Bocha AI Search (https://bochaai.com)
BOCHA_API_KEY=

# Aliyun Bailian Web Search (https://bailian.console.aliyun.com/)
BAILIAN_API_KEY=

# Baidu Qianfan (https://console.bce.baidu.com/qianfan/)
QIANFAN_API_KEY=
QIANFAN_SECRET_KEY=
```

- [ ] **Step 5: Verify install**

Run: `uv run python -c "import httpx, dotenv; print(httpx.__version__, dotenv.__name__)"`
Expected: prints two version strings, no errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore .env.example
git commit -m "chore: add httpx and python-dotenv for real search providers"
```

---

## Task 2: `BaseHTTPSearchProvider` and `TokenBucket` (TDD)

**Files:**
- Create: `src/search_discovery/base_provider.py`
- Create: `tests/search_discovery/test_base_provider.py`

- [ ] **Step 1: Write the failing TokenBucket test**

Create `tests/search_discovery/test_base_provider.py`:

```python
import time
from src.search_discovery.base_provider import TokenBucket


def test_token_bucket_first_call_no_sleep():
    bucket = TokenBucket(rpm=60, sleep=lambda _: None)
    bucket.acquire()
    # No assertion needed — the test passes if no exception / no real sleep.


def test_token_bucket_second_call_sleeps_to_interval():
    sleeps: list[float] = []
    bucket = TokenBucket(rpm=60, sleep=lambda s: sleeps.append(s))
    bucket.acquire()
    bucket.acquire()
    assert len(sleeps) == 1
    assert 0.99 <= sleeps[0] <= 1.01  # 60 RPM = 1 second interval


def test_token_bucket_respects_rpm_30():
    sleeps: list[float] = []
    bucket = TokenBucket(rpm=30, sleep=lambda s: sleeps.append(s))
    bucket.acquire()
    bucket.acquire()
    assert len(sleeps) == 1
    assert 1.99 <= sleeps[0] <= 2.01  # 30 RPM = 2 second interval
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/search_discovery/test_base_provider.py -v`
Expected: ImportError or ModuleNotFoundError on `src.search_discovery.base_provider`.

- [ ] **Step 3: Implement `TokenBucket`**

Create `src/search_discovery/base_provider.py`:

```python
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TokenBucket:
    rpm: int
    sleep: Callable[[float], None] = time.sleep
    _last: float = field(default=0.0, init=False)

    def acquire(self) -> None:
        interval = 60.0 / self.rpm
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < interval and self._last > 0:
            self.sleep(interval - elapsed)
        self._last = time.monotonic()
```

Note: `time.sleep` is the default; tests inject a fake `sleep` to avoid real delays.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_base_provider.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Write failing tests for retry / rate-limit / error normalization**

Append to `tests/search_discovery/test_base_provider.py`:

```python
import httpx
import pytest

from src.search_discovery.base_provider import (
    BaseHTTPSearchProvider,
    ProviderError,
    make_error_row,
)


class _FakeProvider(BaseHTTPSearchProvider):
    source_id = "fake"
    rpm_limit = 6000  # effectively no throttling in tests

    def __init__(self, transport: httpx.MockTransport, **kwargs):
        super().__init__(transport=transport, **kwargs)

    @classmethod
    def from_env(cls):
        return cls(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []})))

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request("GET", "https://example.test/search", params={"q": query})

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        return response.json().get("items", [])


def _transport(responder):
    return httpx.MockTransport(responder)


def test_success_returns_rows():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(200, json={"items": [{"title": "x"}]})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows == [{"title": "x"}]


def test_401_returns_auth_failed_row():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(401, json={"err": "no"})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "auth_failed"
    assert rows[0]["error_type"] == "unauthorized"
    assert rows[0]["keyword_category"] == "topic_discovery"


def test_403_returns_auth_failed_row():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(403, json={"err": "no"})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "auth_failed"
    assert rows[0]["error_type"] == "forbidden"


def test_429_with_retry_after_is_retried():
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"err": "limit"})
        return httpx.Response(200, json={"items": [{"title": "ok"}]})

    provider = _FakeProvider(_transport(responder))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert calls["n"] == 3
    assert rows == [{"title": "ok"}]


def test_5xx_retried_then_succeeds():
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, json={"err": "boom"})
        return httpx.Response(200, json={"items": [{"title": "ok"}]})

    sleeps: list[float] = []
    provider = _FakeProvider(_transport(responder), bucket_sleep=lambda s: sleeps.append(s))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert calls["n"] == 2
    assert rows == [{"title": "ok"}]
    # First backoff = 1 second; second would be 2 (not reached).
    assert sleeps and 0.9 <= sleeps[0] <= 1.1


def test_5xx_exhausted_returns_upstream_failed():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(500, json={"err": "boom"})))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "server_error"


def test_timeout_returns_upstream_failed():
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated")

    provider = _FakeProvider(_transport(responder))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "upstream_failed"
    assert rows[0]["error_type"] == "timeout"


def test_parse_error_returns_parse_failed():
    provider = _FakeProvider(_transport(lambda r: httpx.Response(200, text="not json")))
    rows = provider.search_rows("hello", keyword_category="topic_discovery",
                                fetched_at="2026-06-27T10:00:00+08:00")
    assert rows[0]["fetch_status"] == "parse_failed"
    assert rows[0]["error_type"] == "invalid_json"


def test_make_error_row_helper():
    row = make_error_row(source_id="x", query="q", category="tech_project",
                         fetch_status="auth_failed", error_type="unauthorized",
                         fetched_at="2026-06-27T10:00:00+08:00", index=2)
    assert row["source_id"] == "x"
    assert row["fetch_status"] == "auth_failed"
    assert row["query"] == "q"
    assert row["keyword_category"] == "tech_project"
    assert row["title"] == ""
    assert row["url"] == ""
    assert row["result_id"] == "x_error_2"
```

- [ ] **Step 6: Run the new tests and confirm they fail**

Run: `uv run pytest tests/search_discovery/test_base_provider.py -v`
Expected: ImportError on `BaseHTTPSearchProvider`, `ProviderError`, `make_error_row`.

- [ ] **Step 7: Implement `BaseHTTPSearchProvider`**

Add to `src/search_discovery/base_provider.py`:

```python
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx


@dataclass
class TokenBucket:
    rpm: int
    sleep: Callable[[float], None] = time.sleep
    _last: float = field(default=0.0, init=False)

    def acquire(self) -> None:
        interval = 60.0 / self.rpm
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < interval and self._last > 0:
            self.sleep(interval - elapsed)
        self._last = time.monotonic()


class ProviderError(Exception):
    def __init__(self, fetch_status: str, error_type: str):
        super().__init__(f"{fetch_status}: {error_type}")
        self.fetch_status = fetch_status
        self.error_type = error_type


def make_error_row(
    *,
    source_id: str,
    query: str,
    category: str,
    fetch_status: str,
    error_type: str,
    fetched_at: str,
    index: int = 0,
) -> dict:
    return {
        "result_id": f"{source_id}_error_{index}",
        "source_id": source_id,
        "source_role": "",
        "query": query,
        "keyword_category": category,
        "title": "",
        "url": "",
        "domain": "",
        "snippet": "",
        "content_type": "unknown",
        "published_at": "",
        "fetched_at": fetched_at,
        "metrics": {},
        "raw_payload": {},
        "fetch_status": fetch_status,
        "error_type": error_type,
    }


class BaseHTTPSearchProvider:
    """Subclasses set `source_id` and `rpm_limit`, and implement
    `_build_request`, `_parse_response`, and `from_env`."""

    source_id: str = ""
    rpm_limit: int = 60
    timeout_seconds: float = 10.0
    max_retries: int = 3

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        bucket_sleep: Callable[[float], None] | None = None,
    ):
        self._client = httpx.Client(timeout=self.timeout_seconds, transport=transport)
        sleep_fn = bucket_sleep if bucket_sleep is not None else time.sleep
        self._bucket = TokenBucket(rpm=self.rpm_limit, sleep=sleep_fn)

    @classmethod
    def from_env(cls) -> "BaseHTTPSearchProvider | None":
        raise NotImplementedError

    def search_rows(
        self,
        query: str,
        *,
        keyword_category: str = "unknown",
        fetched_at: str = "",
        index: int = 0,
    ) -> list[dict]:
        request = self._build_request(query)
        self._bucket.acquire()
        try:
            response = self._execute_with_retry(request)
        except ProviderError as exc:
            return [make_error_row(
                source_id=self.source_id,
                query=query,
                category=keyword_category,
                fetch_status=exc.fetch_status,
                error_type=exc.error_type,
                fetched_at=fetched_at,
                index=index,
            )]
        return self._parse_response(response, query)

    def _execute_with_retry(self, request: httpx.Request) -> httpx.Response:
        last_exc: ProviderError | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._client.send(request)
            except httpx.TimeoutException:
                last_exc = ProviderError("upstream_failed", "timeout")
                self._backoff(attempt)
                continue
            except httpx.TransportError:
                last_exc = ProviderError("upstream_failed", "network")
                self._backoff(attempt)
                continue

            status = response.status_code
            if status == 401:
                raise ProviderError("auth_failed", "unauthorized")
            if status == 403:
                raise ProviderError("auth_failed", "forbidden")
            if status == 429:
                if attempt < self.max_retries - 1:
                    wait = float(response.headers.get("Retry-After", "1"))
                    self._bucket.sleep(wait)
                    continue
                raise ProviderError("upstream_failed", "rate_limited")
            if 500 <= status < 600:
                last_exc = ProviderError("upstream_failed", "server_error")
                self._backoff(attempt)
                continue
            return response

        if last_exc is not None:
            raise last_exc
        raise ProviderError("upstream_failed", "exhausted")

    def _backoff(self, attempt: int) -> None:
        # 1s, 2s, 4s
        self._bucket.sleep(2 ** attempt)

    def _build_request(self, query: str) -> httpx.Request:
        raise NotImplementedError

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        try:
            return response.json()
        except Exception:
            raise ProviderError("parse_failed", "invalid_json")
```

- [ ] **Step 8: Run all base-provider tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_base_provider.py -v`
Expected: all tests pass (TokenBucket × 3 + BaseHTTPSearchProvider × 9 = 12 tests).

- [ ] **Step 9: Commit**

```bash
git add src/search_discovery/base_provider.py tests/search_discovery/test_base_provider.py
git commit -m "feat: add BaseHTTPSearchProvider with retry, rate limit, error normalization"
```

---

## Task 3: `GitHubSearchProvider` (TDD)

**Files:**
- Create: `src/search_discovery/providers_github.py`
- Create: `tests/search_discovery/test_providers_github.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_providers_github.py`:

```python
import httpx
import pytest

from src.search_discovery.providers_github import GitHubSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert GitHubSearchProvider.from_env() is None


def test_from_env_returns_instance_when_token_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    assert provider is not None
    assert provider.source_id == "github_search"


def test_search_rows_parses_items(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    provider._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "items": [
                {"full_name": "foo/bar", "html_url": "https://github.com/foo/bar",
                 "description": "desc", "stargazers_count": 100}
            ]
        })),
        timeout=provider.timeout_seconds,
    )
    rows = provider.search_rows("agent", keyword_category="tech_project", fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["title"] == "foo/bar"
    assert rows[0]["url"] == "https://github.com/foo/bar"
    assert rows[0]["snippet"] == "desc"
    assert rows[0]["content_type"] == "repo"
    assert rows[0]["metrics"]["stars"] == 100


def test_search_rows_empty_items(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    provider._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"items": []})),
        timeout=provider.timeout_seconds,
    )
    rows = provider.search_rows("nothing")
    assert rows == []


def test_search_rows_skips_items_without_url(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    provider = GitHubSearchProvider.from_env()
    provider._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={
            "items": [
                {"full_name": "ok/x", "html_url": "https://github.com/ok/x", "description": "d"},
                {"full_name": "bad", "html_url": "", "description": "no url"},
            ]
        })),
        timeout=provider.timeout_seconds,
    )
    rows = provider.search_rows("x")
    assert len(rows) == 1
    assert rows[0]["title"] == "ok/x"
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/search_discovery/test_providers_github.py -v`
Expected: ModuleNotFoundError on `src.search_discovery.providers_github`.

- [ ] **Step 3: Implement `GitHubSearchProvider`**

Create `src/search_discovery/providers_github.py`:

```python
import os

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider


class GitHubSearchProvider(BaseHTTPSearchProvider):
    source_id = "github_search"
    rpm_limit = 30  # GitHub secondary rate limit; stay conservative
    timeout_seconds = 10.0

    def __init__(self, *, token: str | None = None, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._token = token

    @classmethod
    def from_env(cls) -> "GitHubSearchProvider | None":
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return None
        return cls(token=token)

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "GET",
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 10},
            headers=self._auth_headers(),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        body = response.json()
        rows: list[dict] = []
        for item in body.get("items", []):
            url = item.get("html_url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("full_name", ""),
                "url": url,
                "domain": "github.com",
                "snippet": item.get("description", "") or "",
                "content_type": "repo",
                "published_at": "",
                "metrics": {"stars": item.get("stargazers_count", 0)},
            })
        return rows
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_providers_github.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/search_discovery/providers_github.py tests/search_discovery/test_providers_github.py
git commit -m "feat: add GitHubSearchProvider"
```

---

## Task 4: `BochaSearchProvider` (TDD)

**Files:**
- Create: `src/search_discovery/providers_bocha.py`
- Create: `tests/search_discovery/test_providers_bocha.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_providers_bocha.py`:

```python
import httpx
import pytest

from src.search_discovery.providers_bocha import BochaSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    assert BochaSearchProvider.from_env() is None


def test_from_env_returns_instance_when_key_present(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "news_api_cn"


def test_search_rows_parses_webpages(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer sk-fake"
        body = request.read()
        import json as _json
        payload = _json.loads(body)
        assert payload["query"] == "AI Agent"
        return httpx.Response(200, json={
            "code": 0,
            "data": {
                "webPages": {
                    "value": [
                        {"name": "标题1", "url": "https://news.example.com/a",
                         "snippet": "摘要1", "datePublished": "2026-06-27"}
                    ]
                }
            }
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("AI Agent", keyword_category="topic_discovery",
                         fetched_at="2026-06-27T10:00:00+08:00")
    assert len(rows) == 1
    assert rows[0]["title"] == "标题1"
    assert rows[0]["url"] == "https://news.example.com/a"
    assert rows[0]["snippet"] == "摘要1"
    assert rows[0]["content_type"] == "news"
    assert rows[0]["published_at"] == "2026-06-27"


def test_search_rows_skips_non_zero_code(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"code": 4001, "msg": "quota"})),
        timeout=p.timeout_seconds,
    )
    from src.search_discovery.base_provider import ProviderError
    with pytest.raises(ProviderError) as exc:
        p.search_rows("x")
    assert exc.value.fetch_status == "upstream_failed"


def test_search_rows_empty_results(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-fake")
    p = BochaSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"code": 0, "data": {"webPages": {"value": []}}})),
        timeout=p.timeout_seconds,
    )
    assert p.search_rows("x") == []
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/search_discovery/test_providers_bocha.py -v`
Expected: ModuleNotFoundError on `src.search_discovery.providers_bocha`.

- [ ] **Step 3: Implement `BochaSearchProvider`**

Create `src/search_discovery/providers_bocha.py`:

```python
import json
import os
from urllib.parse import urlparse

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, ProviderError


class BochaSearchProvider(BaseHTTPSearchProvider):
    source_id = "news_api_cn"  # keep existing ID for config compatibility
    rpm_limit = 60
    timeout_seconds = 10.0

    ENDPOINT = "https://api.bochaai.com/v1/web-search"

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "BochaSearchProvider | None":
        key = os.getenv("BOCHA_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            self.ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"query": query, "summary": True, "count": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        body = response.json()
        code = body.get("code", 0)
        if code != 0:
            raise ProviderError("upstream_failed", f"bocha_code_{code}")
        webpages = body.get("data", {}).get("webPages", {}).get("value", [])
        rows: list[dict] = []
        for item in webpages:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("name", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("snippet", "") or "",
                "content_type": "news",
                "published_at": item.get("datePublished", "") or "",
                "metrics": {},
            })
        return rows
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_providers_bocha.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/search_discovery/providers_bocha.py tests/search_discovery/test_providers_bocha.py
git commit -m "feat: add BochaSearchProvider for Chinese web search"
```

---

## Task 5: `BailianWebSearchProvider` (TDD)

**Files:**
- Create: `src/search_discovery/providers_bailian.py`
- Create: `tests/search_discovery/test_providers_bailian.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_providers_bailian.py`:

```python
import httpx
import pytest

from src.search_discovery.providers_bailian import BailianWebSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("BAILIAN_API_KEY", raising=False)
    assert BailianWebSearchProvider.from_env() is None


def test_from_env_returns_instance(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "juejin_content"


def test_search_rows_parses_results(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer sk-fake"
        return httpx.Response(200, json={
            "output": {
                "search_results": [
                    {"title": "深度文章", "url": "https://example.com/a",
                     "snippet": "摘要", "content_type": "article"}
                ]
            }
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("RAG")
    assert len(rows) == 1
    assert rows[0]["title"] == "深度文章"
    assert rows[0]["content_type"] == "article"


def test_search_rows_empty(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-fake")
    p = BailianWebSearchProvider.from_env()
    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"output": {"search_results": []}})),
        timeout=p.timeout_seconds,
    )
    assert p.search_rows("x") == []
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/search_discovery/test_providers_bailian.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `BailianWebSearchProvider`**

Create `src/search_discovery/providers_bailian.py`:

```python
import json
import os
from urllib.parse import urlparse

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider


class BailianWebSearchProvider(BaseHTTPSearchProvider):
    source_id = "juejin_content"  # keep existing ID; this provider replaces the slot
    rpm_limit = 60
    timeout_seconds = 10.0

    ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/apps/web_search"

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "BailianWebSearchProvider | None":
        key = os.getenv("BAILIAN_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            self.ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"query": query, "top_k": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        body = response.json()
        results = body.get("output", {}).get("search_results", [])
        rows: list[dict] = []
        for item in results:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("title", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("snippet", "") or "",
                "content_type": item.get("content_type", "article"),
                "published_at": item.get("published_at", "") or "",
                "metrics": {},
            })
        return rows
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_providers_bailian.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/search_discovery/providers_bailian.py tests/search_discovery/test_providers_bailian.py
git commit -m "feat: add BailianWebSearchProvider"
```

---

## Task 6: `QianfanSearchProvider` (TDD)

The Qianfan AppBuilder search needs an OAuth `access_token` exchange first. Cache the token on the instance and re-fetch when expired.

**Files:**
- Create: `src/search_discovery/providers_qianfan.py`
- Create: `tests/search_discovery/test_providers_qianfan.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_providers_qianfan.py`:

```python
import httpx
import pytest

from src.search_discovery.providers_qianfan import QianfanSearchProvider


def _transport(responder):
    return httpx.MockTransport(responder)


def test_from_env_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("QIANFAN_API_KEY", raising=False)
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    assert QianfanSearchProvider.from_env() is None


def test_from_env_returns_none_when_only_one(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.delenv("QIANFAN_SECRET_KEY", raising=False)
    assert QianfanSearchProvider.from_env() is None


def test_from_env_returns_instance(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()
    assert p is not None
    assert p.source_id == "baidu_qianfan_search"


def test_search_rows_exchanges_token_then_calls(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()

    token_calls = {"n": 0}
    search_calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        if "oauth/2.0/token" in str(request.url):
            token_calls["n"] += 1
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 2592000})
        search_calls["n"] += 1
        assert request.headers.get("Authorization") == "Bearer tok-1"
        return httpx.Response(200, json={
            "errno": 0,
            "data": {
                "items": [
                    {"title": "百度结果", "url": "https://example.com/x", "abstract": "摘要"}
                ]
            }
        })

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    rows = p.search_rows("AI", keyword_category="topic_discovery",
                         fetched_at="2026-06-27T10:00:00+08:00")
    assert token_calls["n"] == 1
    assert search_calls["n"] == 1
    assert len(rows) == 1
    assert rows[0]["title"] == "百度结果"
    assert rows[0]["content_type"] == "news"


def test_search_rows_reuses_cached_token(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()
    p._access_token = "cached-tok"
    p._token_expires_at = 9_999_999_999  # far future

    search_calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        search_calls["n"] += 1
        if "oauth" in str(request.url):
            return httpx.Response(200, json={"access_token": "new", "expires_in": 1})
        assert request.headers.get("Authorization") == "Bearer cached-tok"
        return httpx.Response(200, json={"errno": 0, "data": {"items": []}})

    p._client = httpx.Client(transport=_transport(responder), timeout=p.timeout_seconds)
    p.search_rows("x")
    assert search_calls["n"] == 1


def test_search_rows_raises_on_nonzero_errno(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "ak")
    monkeypatch.setenv("QIANFAN_SECRET_KEY", "sk")
    p = QianfanSearchProvider.from_env()
    p._access_token = "tok"
    p._token_expires_at = 9_999_999_999

    p._client = httpx.Client(
        transport=_transport(lambda r: httpx.Response(200, json={"errno": 100, "msg": "err"})),
        timeout=p.timeout_seconds,
    )
    from src.search_discovery.base_provider import ProviderError
    with pytest.raises(ProviderError) as exc:
        p.search_rows("x")
    assert exc.value.fetch_status == "upstream_failed"
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/search_discovery/test_providers_qianfan.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `QianfanSearchProvider`**

Create `src/search_discovery/providers_qianfan.py`:

```python
import json
import os
import time
from urllib.parse import urlparse

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider, ProviderError


class QianfanSearchProvider(BaseHTTPSearchProvider):
    source_id = "baidu_qianfan_search"
    rpm_limit = 60
    timeout_seconds = 10.0

    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    SEARCH_URL = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/plugin/search"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        transport: httpx.BaseTransport | None = None,
        clock=time.time,
    ):
        super().__init__(transport=transport)
        self._api_key = api_key
        self._secret_key = secret_key
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._clock = clock

    @classmethod
    def from_env(cls) -> "QianfanSearchProvider | None":
        api_key = os.getenv("QIANFAN_API_KEY")
        secret_key = os.getenv("QIANFAN_SECRET_KEY")
        if not api_key or not secret_key:
            return None
        return cls(api_key=api_key, secret_key=secret_key)

    def _ensure_token(self) -> None:
        if self._access_token and self._clock() < self._token_expires_at:
            return
        request = httpx.Request(
            "GET",
            self.TOKEN_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": self._secret_key,
            },
        )
        response = self._client.send(request)
        if response.status_code != 200:
            raise ProviderError("auth_failed", "token_exchange_failed")
        body = response.json()
        self._access_token = body["access_token"]
        self._token_expires_at = self._clock() + int(body.get("expires_in", 2592000)) - 60

    def _build_request(self, query: str) -> httpx.Request:
        self._ensure_token()
        return httpx.Request(
            "POST",
            self.SEARCH_URL,
            params={"access_token": self._access_token},
            headers={"Content-Type": "application/json"},
            content=json.dumps({"query": query, "count": 10}),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]:
        body = response.json()
        errno = body.get("errno", 0)
        if errno != 0:
            raise ProviderError("upstream_failed", f"qianfan_errno_{errno}")
        items = body.get("data", {}).get("items", [])
        rows: list[dict] = []
        for item in items:
            url = item.get("url", "")
            if not url:
                continue
            rows.append({
                "title": item.get("title", ""),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": item.get("abstract", "") or "",
                "content_type": "news",
                "published_at": item.get("publishTime", "") or "",
                "metrics": {},
            })
        return rows
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_providers_qianfan.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/search_discovery/providers_qianfan.py tests/search_discovery/test_providers_qianfan.py
git commit -m "feat: add QianfanSearchProvider with token caching"
```

---

## Task 7: Wire CLI assembly + fallback injection

**Files:**
- Modify: `src/search_discovery/providers.py` (around line 43-75)
- Modify: `src/search_discovery/cli.py` (replace `_default_mock_registry()` and add registry builder)
- Create: `tests/search_discovery/test_cli_fallback.py`

- [ ] **Step 1: Update `providers.py` for new search_rows signature and pass fetch_status through**

Edit `src/search_discovery/providers.py`. Apply three changes:

**1a.** Update the `SearchProvider` Protocol to accept optional kwargs:

```python
class SearchProvider(Protocol):
    source_id: str

    def search_rows(self, query: str, **kwargs) -> list[dict[str, object]]:
        raise NotImplementedError
```

**1b.** Update `MockProvider.search_rows` to accept and ignore kwargs:

```python
@dataclass
class MockProvider:
    source_id: str
    rows: list[dict[str, object]]

    def search_rows(self, query: str, **kwargs) -> list[dict[str, object]]:
        return self.rows
```

**1c.** Update `SearchProviderRegistry.search` to forward metadata to `search_rows` and replace `normalize_provider_rows` to read `fetch_status` / `error_type` / `result_id` from row dicts:

```python
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
        index: int = 0,
    ) -> list[SearchResult]:
        provider = self._providers.get(source_id)
        if provider is None:
            return []
        rows = provider.search_rows(
            query, keyword_category=keyword_category, fetched_at=fetched_at, index=index,
        )
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
            result_id=str(row.get("result_id", f"{source_id}_{index:03d}")),
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
            fetch_status=str(row.get("fetch_status", "ok")),
            error_type=row.get("error_type"),
        )
        if result.fetch_status == "ok" and not result.has_usable_detail():
            continue
        results.append(result)
    return results
```

- [ ] **Step 2: Write failing fallback tests**

Create `tests/search_discovery/test_cli_fallback.py`:

```python
import json

from src.search_discovery.cli import _build_registry, _emit_unavailable_markers
from src.search_discovery.types import CreatorProfile


def _profile():
    return CreatorProfile.from_dict({
        "creator_id": "t", "role": "科技博主", "profile_type": "tech_ai_creator",
        "track_tags": ["AI"], "custom_keywords": ["Agent"], "content_modes": [],
    })


def test_build_registry_uses_mock_when_no_keys(monkeypatch):
    for key in ("GITHUB_TOKEN", "BOCHA_API_KEY", "BAILIAN_API_KEY",
                "QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    registry = _build_registry()
    for sid in ("github_search", "news_api_cn", "juejin_content", "baidu_qianfan_search"):
        assert sid in registry._providers


def test_emit_unavailable_markers_returns_four_rows():
    rows = _emit_unavailable_markers(
        registry_source_ids=["github_search", "news_api_cn", "juejin_content", "baidu_qianfan_search"],
        query="AI", category="topic_discovery", fetched_at="2026-06-27T10:00:00+08:00",
        index=7,
    )
    assert len(rows) == 4
    assert all(r["fetch_status"] == "mock_unavailable" for r in rows)
    assert all(r["error_type"] == "missing_key" for r in rows)
    assert all(r["result_id"].endswith("_7") for r in rows)


def test_build_registry_uses_real_when_keys_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    for key in ("BOCHA_API_KEY", "BAILIAN_API_KEY",
                "QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    registry = _build_registry()
    from src.search_discovery.providers_github import GitHubSearchProvider
    assert isinstance(registry._providers["github_search"], GitHubSearchProvider)
    # others should be mock
    from src.search_discovery.providers import MockProvider
    assert isinstance(registry._providers["news_api_cn"], MockProvider)
```

- [ ] **Step 3: Run tests and confirm they fail**

Run: `uv run pytest tests/search_discovery/test_cli_fallback.py -v`
Expected: ImportError on `_build_registry` / `_emit_unavailable_markers` from `cli`.

- [ ] **Step 4: Implement `_build_registry` and `_emit_unavailable_markers` in `cli.py`**

Replace `src/search_discovery/cli.py` with the following content:

```python
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.search_discovery.base_provider import make_error_row
from src.search_discovery.config import plan_sources_for_category, profile_source_weights, source_registry
from src.search_discovery.discovery import cluster_results
from src.search_discovery.enrich import enrich_results
from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.keywords import classify_keywords, generate_query_bundles
from src.search_discovery.providers import MockProvider, SearchProviderRegistry
from src.search_discovery.providers_bailian import BailianWebSearchProvider
from src.search_discovery.providers_bocha import BochaSearchProvider
from src.search_discovery.providers_github import GitHubSearchProvider
from src.search_discovery.providers_qianfan import QianfanSearchProvider
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CreatorProfile

_REAL_PROVIDER_CLASSES = [
    GitHubSearchProvider,
    BochaSearchProvider,
    BailianWebSearchProvider,
    QianfanSearchProvider,
]

_SLOT_IDS = ("github_search", "news_api_cn", "juejin_content", "baidu_qianfan_search")


def _build_registry() -> SearchProviderRegistry:
    providers: dict[str, object] = {}
    for cls in _REAL_PROVIDER_CLASSES:
        real = cls.from_env()
        if real is not None:
            providers[cls.source_id] = real
        else:
            providers[cls.source_id] = MockProvider(cls.source_id, rows=[])
    return SearchProviderRegistry(providers)


def _emit_unavailable_markers(
    *,
    registry_source_ids: list[str],
    query: str,
    category: str,
    fetched_at: str,
    index: int,
) -> list[dict]:
    return [
        make_error_row(
            source_id=sid,
            query=query,
            category=category,
            fetch_status="mock_unavailable",
            error_type="missing_key",
            fetched_at=fetched_at,
            index=index,
        )
        for sid in registry_source_ids
    ]


def run_discovery_command(root: Path, profile_path: Path, render_report: bool = False) -> dict[str, int]:
    load_dotenv()
    profile = CreatorProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    generated_at = _now_shanghai()
    categories = classify_keywords(profile)
    bundles = generate_query_bundles(profile, categories=categories)
    sources = source_registry()
    registry = _build_registry()
    results = []
    unavailable_ids = {
        sid for sid in _SLOT_IDS
        if isinstance(registry._providers.get(sid), MockProvider)
    }
    counter = 0
    for bundle in bundles:
        planned_sources = plan_sources_for_category(profile.profile_type, bundle.category)
        for planned_source in planned_sources:
            source = sources[planned_source.source_id]
            for query in bundle.queries:
                if planned_source.source_id in unavailable_ids:
                    results.extend(_emit_unavailable_markers(
                        registry_source_ids=[planned_source.source_id],
                        query=query, category=bundle.category, fetched_at=generated_at,
                        index=counter,
                    ))
                else:
                    results.extend(
                        registry.search(
                            source_id=planned_source.source_id,
                            source_role=source.source_role,
                            query=query,
                            keyword_category=bundle.category,
                            fetched_at=generated_at,
                            index=counter,
                        )
                    )
                counter += 1
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

- [ ] **Step 5: Run the new tests and confirm they pass**

Run: `uv run pytest tests/search_discovery/test_cli_fallback.py -v`
Expected: 3 tests pass.

- [ ] **Step 6: Run the full search_discovery suite and ensure nothing regressed**

Run: `uv run pytest tests/search_discovery/ -v`
Expected: all tests pass. If `test_cli.py` was using `_default_mock_registry` and breaks, the function no longer exists — delete that test's reference (the existing `test_cli.py` calls `run_discovery_command` directly, which still works since we kept the same signature; verify it still passes).

- [ ] **Step 7: Smoke test the CLI with no keys configured**

Run:
```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```
Expected: JSON output with counts, exit code 0. Report still renders (may be empty topic list, but file exists). The raw JSONL contains `fetch_status: "mock_unavailable"` rows.

- [ ] **Step 8: Commit**

```bash
git add src/search_discovery/cli.py src/search_discovery/providers.py tests/search_discovery/test_cli_fallback.py
git commit -m "feat: wire real providers with mock-key fallback in CLI"
```

---

## Task 8: Quickstart docs

**Files:**
- Create: `docs/superpowers/integrations/github-quickstart.md`
- Create: `docs/superpowers/integrations/bocha-quickstart.md`
- Create: `docs/superpowers/integrations/bailian-quickstart.md`
- Create: `docs/superpowers/integrations/qianfan-quickstart.md`

- [ ] **Step 1: Write GitHub quickstart**

Create `docs/superpowers/integrations/github-quickstart.md`:

```markdown
# GitHub Search Quickstart

## Get a token

1. Open https://github.com/settings/tokens
2. Generate a classic token; no scopes required for `/search`.
3. Copy the token (starts with `ghp_`).

## Configure

In `.env`:

```bash
GITHUB_TOKEN=ghp_your_token_here
```

Without a token the provider still works at 60 req/h; with a token, 5000 req/h.

## Verify

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

In `data/search_discovery/raw/search_results.jsonl`, look for entries with
`source_id: "github_search"` and `fetch_status: "ok"`.
```

- [ ] **Step 2: Write Bocha quickstart**

Create `docs/superpowers/integrations/bocha-quickstart.md`:

```markdown
# Bocha AI Search Quickstart

## Get an API key

1. Open https://bochaai.com and register.
2. From the console, create an API key (free tier available).

## Configure

In `.env`:

```bash
BOCHA_API_KEY=sk-your_key_here
```

## Verify

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

In `data/search_discovery/raw/search_results.jsonl`, look for entries with
`source_id: "news_api_cn"` and `fetch_status: "ok"`.
```

- [ ] **Step 3: Write Bailian quickstart**

Create `docs/superpowers/integrations/bailian-quickstart.md`:

```markdown
# Aliyun Bailian Web Search Quickstart

## Get an API key

1. Open https://bailian.console.aliyun.com/ and sign in.
2. Enable the **Web Search** capability on the model you intend to use.
3. Generate an API key under "API-KEY 管理".

## Configure

In `.env`:

```bash
BAILIAN_API_KEY=sk-your_key_here
```

## Verify

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

In `data/search_discovery/raw/search_results.jsonl`, look for entries with
`source_id: "juejin_content"` and `fetch_status: "ok"`.
```

- [ ] **Step 4: Write Qianfan quickstart**

Create `docs/superpowers/integrations/qianfan-quickstart.md`:

```markdown
# Baidu Qianfan Search Quickstart

## Get AK / SK

1. Open https://console.bce.baidu.com/qianfan/ and create an app.
2. From "应用接入" copy the **API Key (AK)** and **Secret Key (SK)**.
3. Enable the **AppBuilder 搜索增强** capability.

## Configure

In `.env`:

```bash
QIANFAN_API_KEY=your_ak_here
QIANFAN_SECRET_KEY=your_sk_here
```

The provider exchanges AK/SK for an `access_token` at startup and caches it
until ~60s before expiry.

## Verify

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

In `data/search_discovery/raw/search_results.jsonl`, look for entries with
`source_id: "baidu_qianfan_search"` and `fetch_status: "ok"`.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/integrations/
git commit -m "docs: add quickstart guides for each search provider"
```

---

## Final verification

Run all four commands and confirm each passes:

- [ ] **Test suite green**

```bash
uv run pytest tests/search_discovery/ -q
```
Expected: all tests pass.

- [ ] **CLI smoke test (no keys)**

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```
Expected: exit code 0, raw JSONL contains `mock_unavailable` markers, report renders.

- [ ] **.env not committed**

```bash
git status --porcelain | grep -E '^\?\? \.env$'
```
Expected: no output (file is ignored).

- [ ] **Inspect a real-source run**

If at least one of `GITHUB_TOKEN`, `BOCHA_API_KEY`, `BAILIAN_API_KEY`,
`QIANFAN_API_KEY`+`QIANFAN_SECRET_KEY` is configured, re-run the CLI and
verify the corresponding `source_id` in `data/search_discovery/raw/search_results.jsonl`
has `fetch_status: "ok"` and at least one row with non-empty `url`.

---

## Notes for the implementer

- The `MockProvider` from the existing codebase stays untouched. The CLI no longer uses `_default_mock_registry`; that function is removed in Task 7.
- `SearchResult.fetch_status == "ok"` is the default; only error paths need to set it explicitly. The mock-unavailable markers use `fetch_status="mock_unavailable"` and `error_type="missing_key"`.
- Subclasses should not implement `search_rows` directly — they implement `_build_request` and `_parse_response`. The base class wires them together with retry and rate limiting.
- For testing time-sensitive behavior, inject `clock` (Qianfan) or `sleep`/`bucket_sleep` (base) — never patch `time` globally.