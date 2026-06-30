# Search API Config Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI assistant that helps users configure search API keys, saves them to `.env`, and immediately runs a lightweight connection test after each confirmed save.

**Architecture:** Add a small configuration subsystem under `src/search_discovery`: source metadata, safe `.env` read/write helpers, provider connectivity tests, and an interactive CLI module. Reuse existing provider `from_env()` and `search_rows()` methods so connectivity testing matches the real discovery pipeline.

**Tech Stack:** Python standard library, `python-dotenv` already in use, existing `httpx` providers, `uv run pytest`.

---

## File Structure

- Create `src/search_discovery/api_config.py`
  - Defines all configurable search sources, required env keys, signup URLs, descriptions, and test queries.
  - Owns key masking and source lookup.

- Create `src/search_discovery/env_file.py`
  - Reads `.env` without exposing secret values.
  - Creates `.env` from `.env.example` if missing.
  - Upserts keys while preserving unrelated lines and comments.

- Create `src/search_discovery/connectivity.py`
  - Tests one configured provider with a lightweight query.
  - Returns structured status: `ok`, `missing_key`, `auth_failed`, `upstream_failed`, `parse_failed`, `empty_result`.

- Create `src/search_discovery/config_api.py`
  - CLI entry point for `--list`, `--set SOURCE_ID`, `--wizard`, and `--test SOURCE_ID`.
  - After user confirms saving a key, automatically runs `connectivity.test_source_connection()`.

- Tests:
  - Create `tests/search_discovery/test_api_config.py`
  - Create `tests/search_discovery/test_env_file.py`
  - Create `tests/search_discovery/test_connectivity.py`
  - Create `tests/search_discovery/test_config_api.py`

## Task 1: Define API Source Metadata

**Files:**
- Create: `src/search_discovery/api_config.py`
- Test: `tests/search_discovery/test_api_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_api_config.py`:

```python
from src.search_discovery.api_config import api_source_configs, get_api_source_config, mask_secret


def test_api_source_configs_include_all_configurable_sources():
    configs = api_source_configs()

    assert configs["github_search"].env_keys == ["GITHUB_TOKEN"]
    assert configs["baidu_qianfan_search"].env_keys == ["QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"]
    assert configs["tavily_search"].env_keys == ["TAVILY_API_KEY"]
    assert configs["tianapi_news"].test_query == "AI Agent 最新进展"


def test_get_api_source_config_rejects_unknown_source():
    try:
        get_api_source_config("missing_source")
    except KeyError as exc:
        assert "missing_source" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_mask_secret_keeps_short_preview_only():
    assert mask_secret("") == "<empty>"
    assert mask_secret("abc") == "***"
    assert mask_secret("tvly_1234567890") == "tvly****7890"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_api_config.py -q
```

Expected: FAIL because `api_config.py` does not exist.

- [ ] **Step 3: Implement metadata module**

Create `src/search_discovery/api_config.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiSourceConfig:
    source_id: str
    display_name: str
    env_keys: list[str]
    signup_url: str
    description: str
    test_query: str = "AI Agent 最新进展"


def api_source_configs() -> dict[str, ApiSourceConfig]:
    return {
        "github_search": ApiSourceConfig(
            source_id="github_search",
            display_name="GitHub Search",
            env_keys=["GITHUB_TOKEN"],
            signup_url="https://github.com/settings/tokens",
            description="Open-source repository and project discovery.",
            test_query="AI Agent stars:>50 pushed:>2025-01-01",
        ),
        "news_api_cn": ApiSourceConfig(
            source_id="news_api_cn",
            display_name="Bocha AI Search",
            env_keys=["BOCHA_API_KEY"],
            signup_url="https://bochaai.com",
            description="AI-friendly China web and news search.",
        ),
        "juejin_content": ApiSourceConfig(
            source_id="juejin_content",
            display_name="Aliyun Bailian Web Search",
            env_keys=["BAILIAN_API_KEY"],
            signup_url="https://bailian.console.aliyun.com/",
            description="Chinese technical articles and web search slot.",
        ),
        "baidu_qianfan_search": ApiSourceConfig(
            source_id="baidu_qianfan_search",
            display_name="Baidu Qianfan Search",
            env_keys=["QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"],
            signup_url="https://console.bce.baidu.com/qianfan/",
            description="Domestic general web, blog, Q&A, and news search.",
        ),
        "tianapi_news": ApiSourceConfig(
            source_id="tianapi_news",
            display_name="TianAPI News",
            env_keys=["TIANAPI_KEY"],
            signup_url="https://www.tianapi.com/",
            description="China news facts, source names, and publish times.",
        ),
        "tavily_search": ApiSourceConfig(
            source_id="tavily_search",
            display_name="Tavily Search",
            env_keys=["TAVILY_API_KEY"],
            signup_url="https://app.tavily.com/home",
            description="AI-friendly web/news search with summaries and raw content.",
        ),
        "qiniu_web_search": ApiSourceConfig(
            source_id="qiniu_web_search",
            display_name="Qiniu Web Search",
            env_keys=["QINIU_WEB_SEARCH_API_KEY"],
            signup_url="https://www.qiniu.com/",
            description="Domestic web-search fallback source.",
        ),
    }


def get_api_source_config(source_id: str) -> ApiSourceConfig:
    configs = api_source_configs()
    if source_id not in configs:
        raise KeyError(f"Unknown API source: {source_id}")
    return configs[source_id]


def mask_secret(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return "***"
    return f"{value[:4]}****{value[-4:]}"
```

- [ ] **Step 4: Run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_api_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/api_config.py tests/search_discovery/test_api_config.py
git commit -m "feat: define search api config metadata"
```

## Task 2: Add Safe `.env` File Helpers

**Files:**
- Create: `src/search_discovery/env_file.py`
- Test: `tests/search_discovery/test_env_file.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_env_file.py`:

```python
from src.search_discovery.env_file import ensure_env_file, read_env_values, upsert_env_values


def test_ensure_env_file_copies_example_when_missing(tmp_path):
    example = tmp_path / ".env.example"
    target = tmp_path / ".env"
    example.write_text("TAVILY_API_KEY=\n", encoding="utf-8")

    created = ensure_env_file(target, example)

    assert created is True
    assert target.read_text(encoding="utf-8") == "TAVILY_API_KEY=\n"


def test_read_env_values_ignores_comments_and_blank_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\n\nTAVILY_API_KEY=tvly_fake\nEMPTY=\n", encoding="utf-8")

    values = read_env_values(env_path)

    assert values == {"TAVILY_API_KEY": "tvly_fake", "EMPTY": ""}


def test_upsert_env_values_preserves_comments_and_updates_existing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# Tavily\nTAVILY_API_KEY=old\n\nGITHUB_TOKEN=\n", encoding="utf-8")

    upsert_env_values(env_path, {"TAVILY_API_KEY": "new", "BOCHA_API_KEY": "bocha"})

    assert env_path.read_text(encoding="utf-8") == (
        "# Tavily\n"
        "TAVILY_API_KEY=new\n"
        "\n"
        "GITHUB_TOKEN=\n"
        "BOCHA_API_KEY=bocha\n"
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_env_file.py -q
```

Expected: FAIL because `env_file.py` does not exist.

- [ ] **Step 3: Implement env helpers**

Create `src/search_discovery/env_file.py`:

```python
from pathlib import Path


def ensure_env_file(env_path: Path, example_path: Path) -> bool:
    if env_path.exists():
        return False
    env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def read_env_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def upsert_env_values(env_path: Path, updates: dict[str, str]) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _value = stripped.split("=", 1)
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    for key, value in remaining.items():
        output.append(f"{key}={value}")
    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_env_file.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/env_file.py tests/search_discovery/test_env_file.py
git commit -m "feat: add env file helpers for api config"
```

## Task 3: Add Provider Connectivity Tester

**Files:**
- Create: `src/search_discovery/connectivity.py`
- Test: `tests/search_discovery/test_connectivity.py`

- [ ] **Step 1: Write failing tests**

Create `tests/search_discovery/test_connectivity.py`:

```python
from dataclasses import dataclass

from src.search_discovery.connectivity import ConnectionTestResult, test_source_connection
from src.search_discovery.providers import MockProvider, SearchProviderRegistry


@dataclass
class FakeProvider:
    source_id: str
    rows: list[dict[str, object]]

    def search_rows(self, query, **kwargs):
        return self.rows


def test_test_source_connection_reports_missing_key_for_mock_provider():
    registry = SearchProviderRegistry([MockProvider("tavily_search", rows=[])])

    result = test_source_connection("tavily_search", registry=registry, query="AI Agent 最新进展")

    assert result == ConnectionTestResult(
        source_id="tavily_search",
        status="missing_key",
        message="tavily_search is not configured.",
        result_count=0,
        error_type="missing_key",
    )


def test_test_source_connection_reports_ok_when_rows_returned():
    registry = SearchProviderRegistry([
        FakeProvider("tavily_search", [{"title": "A", "url": "https://example.com", "snippet": "summary"}])
    ])

    result = test_source_connection("tavily_search", registry=registry, query="AI Agent 最新进展")

    assert result.status == "ok"
    assert result.result_count == 1
    assert "connected successfully" in result.message


def test_test_source_connection_reports_provider_error_row():
    registry = SearchProviderRegistry([
        FakeProvider(
            "baidu_qianfan_search",
            [{"fetch_status": "auth_failed", "error_type": "token_exchange_failed", "title": "", "url": ""}],
        )
    ])

    result = test_source_connection("baidu_qianfan_search", registry=registry, query="AI Agent 最新进展")

    assert result.status == "auth_failed"
    assert result.error_type == "token_exchange_failed"
    assert "token_exchange_failed" in result.message
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_connectivity.py -q
```

Expected: FAIL because `connectivity.py` does not exist.

- [ ] **Step 3: Implement connectivity tester**

Create `src/search_discovery/connectivity.py`:

```python
from dataclasses import dataclass

from src.search_discovery.providers import MockProvider, SearchProviderRegistry


@dataclass(frozen=True)
class ConnectionTestResult:
    source_id: str
    status: str
    message: str
    result_count: int = 0
    error_type: str = ""


def test_source_connection(
    source_id: str,
    *,
    registry: SearchProviderRegistry,
    query: str,
) -> ConnectionTestResult:
    provider = registry.providers.get(source_id)
    if provider is None or isinstance(provider, MockProvider):
        return ConnectionTestResult(
            source_id=source_id,
            status="missing_key",
            message=f"{source_id} is not configured.",
            error_type="missing_key",
        )

    rows = provider.search_rows(query, keyword_category="connection_test", fetched_at="", index=0)
    error_rows = [row for row in rows if str(row.get("fetch_status", "ok")) != "ok"]
    if error_rows:
        first = error_rows[0]
        status = str(first.get("fetch_status", "upstream_failed"))
        error_type = str(first.get("error_type", "unknown"))
        return ConnectionTestResult(
            source_id=source_id,
            status=status,
            message=f"{source_id} {status}: {error_type}",
            error_type=error_type,
        )
    if not rows:
        return ConnectionTestResult(
            source_id=source_id,
            status="empty_result",
            message=f"{source_id} connected but returned no results.",
            result_count=0,
        )
    return ConnectionTestResult(
        source_id=source_id,
        status="ok",
        message=f"{source_id} connected successfully, returned {len(rows)} results.",
        result_count=len(rows),
    )
```

- [ ] **Step 4: Run tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_connectivity.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/connectivity.py tests/search_discovery/test_connectivity.py
git commit -m "feat: add api connectivity tester"
```

## Task 4: Add Config API CLI

**Files:**
- Create: `src/search_discovery/config_api.py`
- Test: `tests/search_discovery/test_config_api.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/search_discovery/test_config_api.py`:

```python
from pathlib import Path

from src.search_discovery.config_api import run_config_api_command
from src.search_discovery.connectivity import ConnectionTestResult


def test_list_command_masks_configured_keys(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("TAVILY_API_KEY=tvly_1234567890\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = run_config_api_command(["--list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[OK]" in output
    assert "tavily_search" in output
    assert "tvly****7890" in output
    assert "tvly_1234567890" not in output


def test_set_command_saves_then_tests_connection(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("TAVILY_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["tvly_fake", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(
        "src.search_discovery.config_api.test_source_after_save",
        lambda source_id, root: ConnectionTestResult(
            source_id=source_id,
            status="ok",
            message="tavily_search connected successfully, returned 2 results.",
            result_count=2,
        ),
    )

    exit_code = run_config_api_command(["--set", "tavily_search"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "TAVILY_API_KEY=tvly_fake\n"
    assert "[OK] Saved TAVILY_API_KEY" in output
    assert "[TEST] Testing tavily_search" in output
    assert "connected successfully" in output


def test_set_command_does_not_save_when_user_declines(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("TAVILY_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["tvly_fake", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    exit_code = run_config_api_command(["--set", "tavily_search"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "TAVILY_API_KEY=\n"
    assert "Cancelled" in output
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_config_api.py -q
```

Expected: FAIL because `config_api.py` does not exist.

- [ ] **Step 3: Implement CLI command module**

Create `src/search_discovery/config_api.py`:

```python
import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.search_discovery.api_config import api_source_configs, get_api_source_config, mask_secret
from src.search_discovery.cli import _build_registry
from src.search_discovery.connectivity import ConnectionTestResult, test_source_connection
from src.search_discovery.env_file import ensure_env_file, read_env_values, upsert_env_values


def run_config_api_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--set", dest="set_source")
    parser.add_argument("--test", dest="test_source")
    parser.add_argument("--wizard", action="store_true")
    args = parser.parse_args(argv)

    root = Path(".")
    env_path = root / ".env"
    example_path = root / ".env.example"
    ensure_env_file(env_path, example_path)

    if args.list:
        return _list_sources(env_path)
    if args.set_source:
        return _set_source(args.set_source, root, env_path)
    if args.test_source:
        result = test_source_after_save(args.test_source, root)
        _print_test_result(result)
        return 0 if result.status == "ok" else 1
    if args.wizard:
        return _wizard(root, env_path)

    parser.print_help()
    return 1


def _list_sources(env_path: Path) -> int:
    values = read_env_values(env_path)
    print("Search API Configuration\n")
    for source_id, config in api_source_configs().items():
        missing = [key for key in config.env_keys if not values.get(key)]
        if missing:
            print(f"[MISS] {source_id:<22} missing: {', '.join(missing)}")
        else:
            masked = ", ".join(f"{key}={mask_secret(values[key])}" for key in config.env_keys)
            print(f"[OK]   {source_id:<22} {masked}")
    return 0


def _set_source(source_id: str, root: Path, env_path: Path) -> int:
    config = get_api_source_config(source_id)
    print(f"Configuring {config.display_name}")
    print(f"Open: {config.signup_url}\n")
    updates = {}
    for key in config.env_keys:
        value = input(f"{key}: ").strip()
        updates[key] = value
    confirmed = input("Save these keys to .env? [y/N] ").strip().lower()
    if confirmed != "y":
        print("Cancelled.")
        return 1
    upsert_env_values(env_path, updates)
    for key in updates:
        print(f"[OK] Saved {key}")
    print(f"[TEST] Testing {source_id} with query: {config.test_query}")
    result = test_source_after_save(source_id, root)
    _print_test_result(result)
    return 0 if result.status == "ok" else 1


def _wizard(root: Path, env_path: Path) -> int:
    values = read_env_values(env_path)
    for source_id, config in api_source_configs().items():
        if all(values.get(key) for key in config.env_keys):
            continue
        code = _set_source(source_id, root, env_path)
        if code != 0:
            return code
        values = read_env_values(env_path)
    return 0


def test_source_after_save(source_id: str, root: Path) -> ConnectionTestResult:
    load_dotenv(root / ".env", override=True)
    config = get_api_source_config(source_id)
    registry = _build_registry()
    return test_source_connection(source_id, registry=registry, query=config.test_query)


def _print_test_result(result: ConnectionTestResult) -> None:
    if result.status == "ok":
        print(f"[OK] {result.message}")
    else:
        print(f"[FAIL] {result.message}")


def main() -> None:
    raise SystemExit(run_config_api_command())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery/test_config_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/search_discovery/config_api.py tests/search_discovery/test_config_api.py
git commit -m "feat: add search api config assistant"
```

## Task 5: End-to-end Verification

**Files:**
- Modify tests only if current provider list changes while implementing earlier tasks.

- [ ] **Step 1: Run all search discovery tests**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery -q
```

Expected: PASS.

- [ ] **Step 2: Verify list command**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.config_api --list
```

Expected: prints all configurable sources and masks any configured values. It must not print a full API key.

- [ ] **Step 3: Verify test command on missing key**

Run:

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.config_api --test tavily_search
```

Expected when `TAVILY_API_KEY` is missing:

```text
[FAIL] tavily_search is not configured.
```

- [ ] **Step 4: Manual smoke test for save-and-test**

Run against a temporary copy of the repo or after backing up `.env`:

```powershell
uv run python -m src.search_discovery.config_api --set tavily_search
```

Expected:

- Prompts for `TAVILY_API_KEY`.
- Asks `Save these keys to .env? [y/N]`.
- After `y`, writes `.env`.
- Immediately prints `[TEST] Testing tavily_search ...`.
- Prints `[OK]` on connection success or `[FAIL]` with provider error type.

- [ ] **Step 5: Commit final test alignment**

```powershell
git status --short
git add src/search_discovery tests/search_discovery
git commit -m "test: verify api config assistant"
```

Do not stage `.env` or generated `data/` files.

## Self-review

- Spec coverage: The plan covers source metadata, safe `.env` editing, list/set/wizard/test commands, masked secrets, and automatic connection testing immediately after confirmed saves.
- Placeholder scan: No task uses open-ended implementation instructions or references undefined helpers.
- Type consistency: `ApiSourceConfig`, `ConnectionTestResult`, `ensure_env_file`, `upsert_env_values`, and `test_source_after_save` are introduced before later tasks use them.
- Safety: `.env` remains ignored, full keys are never printed, and failed tests do not roll back saved keys.

