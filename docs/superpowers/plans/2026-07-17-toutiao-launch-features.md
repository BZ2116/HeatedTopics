# Toutiao Launch Features Implementation Plan — 每日配额 + 自定义关键词

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Toutiao v2 pipeline 加两个上线用法能力——每日配额（默认 3 次，超限报错）与自定义检索关键词（本次替换自动抽取，按输入顺序检索）。

**Architecture:** 新增纯函数模块 `quota.py`（按天计数 JSON）。`pipeline.py` 加 `custom_keywords` 参数（非空则合成 `PersonaKeywordExtraction(source="custom")` 替换自动抽取）与 `on_search_committed` 回调（`not skip_search` 且流程走完时触发一次）。配额编排放 `cli.py`：进流程前 `check_quota`，搜索成功后经回调 `commit_quota`。

**Tech Stack:** Python 3.14, pytest, argparse, 标准库 json/pathlib/datetime。测试用 fake fetcher + monkeypatch，不触网。

**参考规格：** `docs/superpowers/specs/2026-07-17-toutiao-launch-features-design.md`

---

## File Structure

- **Create** `src/heated_topics_v3/quota.py` — `QuotaState` / `QuotaExceededError` / `load_quota` / `check_quota` / `commit_quota`。单一职责：按天配额状态读写。
- **Create** `tests/test_quota.py` — quota 纯函数单测。
- **Modify** `src/heated_topics_v3/pipeline.py` — `run_toutiao_pipeline_v2` 加 `custom_keywords` + `on_search_committed`。
- **Create** `tests/test_pipeline_custom_keywords.py` — custom 替换 + 回调触发单测。
- **Modify** `src/heated_topics_v3/cli.py` — 新 flag + 配额编排。
- **Create** `tests/test_cli_quota.py` — CLI 配额 exit code / bypass 单测。
- **Modify** `.gitignore` — 忽略 `state/`。
- **Modify** `README.md`（若无则查项目根 README 文件名）— `--skip-quota` 集成说明 + 配额语义。

---

## Task 1: quota.py 配额模块

**Files:**
- Create: `src/heated_topics_v3/quota.py`
- Test: `tests/test_quota.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_quota.py`:

```python
from pathlib import Path

import pytest

from heated_topics_v3.quota import (
    QuotaExceededError,
    QuotaState,
    check_quota,
    commit_quota,
    load_quota,
)


def test_load_quota_missing_file_returns_zero(tmp_path: Path):
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=0)


def test_load_quota_stale_date_resets(tmp_path: Path):
    (tmp_path / "quota").mkdir()
    (tmp_path / "quota" / "u1.json").write_text(
        '{"date": "2026-07-16", "count": 3}', encoding="utf-8"
    )
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=0)


def test_load_quota_same_day_reads_count(tmp_path: Path):
    (tmp_path / "quota").mkdir()
    (tmp_path / "quota" / "u1.json").write_text(
        '{"date": "2026-07-17", "count": 2}', encoding="utf-8"
    )
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=2)


def test_check_quota_under_limit_passes():
    check_quota(QuotaState(date="2026-07-17", count=2), max_per_day=3)


def test_check_quota_at_limit_raises():
    with pytest.raises(QuotaExceededError, match="今日额度已用完"):
        check_quota(QuotaState(date="2026-07-17", count=3), max_per_day=3)


def test_commit_quota_increments_and_persists(tmp_path: Path):
    commit_quota(tmp_path, "u1", "2026-07-17")
    state = load_quota(tmp_path, "u1", "2026-07-17")
    assert state == QuotaState(date="2026-07-17", count=1)
    new = commit_quota(tmp_path, "u1", "2026-07-17")
    assert new == QuotaState(date="2026-07-17", count=2)


def test_commit_quota_stale_date_starts_from_zero(tmp_path: Path):
    (tmp_path / "quota").mkdir()
    (tmp_path / "quota" / "u1.json").write_text(
        '{"date": "2026-07-16", "count": 3}', encoding="utf-8"
    )
    new = commit_quota(tmp_path, "u1", "2026-07-17")
    assert new == QuotaState(date="2026-07-17", count=1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quota.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'heated_topics_v3.quota'`

- [ ] **Step 3: 写实现**

Create `src/heated_topics_v3/quota.py`:

```python
"""Per-user daily quota state.

A quota file `state/quota/{user_id}.json` holds `{"date", "count"}`. A day
rolls over automatically: reading with a different `today` resets count to 0.

check/commit are split on purpose: the pipeline calls `check_quota` BEFORE
running (so the 4th request is rejected without spending a search) and
`commit_quota` AFTER a search flow completes (so failed/short-circuited runs
don't consume the quota).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class QuotaExceededError(Exception):
    """Raised by check_quota when the daily limit is already reached."""


@dataclass(frozen=True)
class QuotaState:
    date: str
    count: int


def _quota_path(state_root: Path, user_id: str) -> Path:
    return Path(state_root) / "quota" / f"{user_id}.json"


def load_quota(state_root: Path, user_id: str, today: str) -> QuotaState:
    """Read quota for today; missing file or stale date both mean count=0."""
    path = _quota_path(state_root, user_id)
    if not path.exists():
        return QuotaState(date=today, count=0)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return QuotaState(date=today, count=0)
    if not isinstance(payload, dict) or payload.get("date") != today:
        return QuotaState(date=today, count=0)
    count = payload.get("count", 0)
    if not isinstance(count, int) or count < 0:
        count = 0
    return QuotaState(date=today, count=count)


def check_quota(state: QuotaState, max_per_day: int) -> None:
    """Raise QuotaExceededError when count has reached the limit. No write."""
    if state.count >= max_per_day:
        raise QuotaExceededError("今日额度已用完")


def commit_quota(state_root: Path, user_id: str, today: str) -> QuotaState:
    """Increment today's count by 1 and persist. Write failures are swallowed
    (best-effort) so a full-disk/permission error never discards a produced run."""
    current = load_quota(state_root, user_id, today)
    new_state = QuotaState(date=today, count=current.count + 1)
    path = _quota_path(state_root, user_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"date": new_state.date, "count": new_state.count}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return new_state
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quota.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 提交**

```bash
git add src/heated_topics_v3/quota.py tests/test_quota.py
git commit -m "feat: add per-user daily quota module"
```

---

## Task 2: pipeline 支持 custom_keywords + on_search_committed

**Files:**
- Modify: `src/heated_topics_v3/pipeline.py`
- Test: `tests/test_pipeline_custom_keywords.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_pipeline_custom_keywords.py`:

```python
import json
import urllib.parse
from pathlib import Path

from heated_topics_v3.pipeline import run_toutiao_pipeline_v2

V2_PROFILE = {
    "user_id": "zhao_001",
    "level1": "科技AI",
    "level2": "AI工具应用",
    "personal": {
        "role": "经管学生视角的AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习", "办公"],
        "value": "真实使用建议",
    },
    "core_keywords": ["AI工具", "AI写作"],
}


def _write_profile(tmp_path: Path, payload: dict | None = None) -> Path:
    path = tmp_path / "zhao_001.json"
    path.write_text(json.dumps(payload or V2_PROFILE, ensure_ascii=False), encoding="utf-8")
    return path


def _static_llm_caller():
    def caller(prompt: str, *, system: str | None = None, **_kwargs) -> str:
        return json.dumps(
            [
                {"keyword": "AI写作工具", "match_expectation": "热榜"},
                {"keyword": "AI办公助手", "match_expectation": "热榜"},
                {"keyword": "Claude Code", "match_expectation": "热榜"},
                {"keyword": "MCP", "match_expectation": "长尾"},
                {"keyword": "Cursor", "match_expectation": "兜底"},
            ],
            ensure_ascii=False,
        )

    return caller


def _recording_fetcher(searched_urls: list[str], hot_board_data: list | None = None):
    def fetcher(url: str, timeout_seconds: int) -> str:
        if "hot-event/hot-board" in url:
            return json.dumps({"status": "success", "data": hot_board_data or []})
        if "so.toutiao.com/search" in url:
            searched_urls.append(urllib.parse.unquote(url))
            return json.dumps({"dom": "", "count": 0})
        if "/i" in url and "/info" in url:
            return json.dumps({"data": {}})
        return ""

    return fetcher


def _detail_fetcher(url: str, timeout_seconds: int) -> str:
    return "<html><body><article><p>body</p></article></body></html>"


def _run(tmp_path, *, custom_keywords=(), on_search_committed=None, fetcher=None,
         hot_board_data=None, searched_urls=None):
    profile_path = _write_profile(tmp_path)
    if fetcher is None:
        searched_urls = searched_urls if searched_urls is not None else []
        fetcher = _recording_fetcher(searched_urls, hot_board_data)
    return run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=tmp_path / "output",
        fetched_at="2026-07-13T10:00:00+08:00",
        hot_board_cache_root=tmp_path / "cache",
        persona_keyword_cache_root=tmp_path / "cache" / "core_keywords",
        llm_cache_root=tmp_path / "cache" / "llm",
        custom_keywords=custom_keywords,
        on_search_committed=on_search_committed,
        fetcher=fetcher,
        article_info_fetcher=fetcher,
        detail_fetcher=_detail_fetcher,
        llm_caller=_static_llm_caller(),
    )


def test_custom_keywords_sets_source_custom(tmp_path: Path):
    result = _run(tmp_path, custom_keywords=("比特币", "美联储"))
    assert result.keyword_source == "custom"
    assert result.keyword_count == 2


def test_custom_keywords_searched_not_auto(tmp_path: Path):
    searched: list[str] = []
    _run(tmp_path, custom_keywords=("比特币", "美联储"), searched_urls=searched)
    joined = " ".join(searched)
    assert "比特币" in joined and "美联储" in joined
    assert "AI写作工具" not in joined and "AI办公助手" not in joined


def test_custom_keywords_preserve_order(tmp_path: Path):
    searched: list[str] = []
    _run(tmp_path, custom_keywords=("比特币", "美联储"), searched_urls=searched)
    first_bitcoin = min(i for i, u in enumerate(searched) if "比特币" in u)
    first_fed = min(i for i, u in enumerate(searched) if "美联储" in u)
    assert first_bitcoin < first_fed


def test_empty_custom_keywords_fallback_to_auto(tmp_path: Path):
    result = _run(tmp_path, custom_keywords=())
    assert result.keyword_source != "custom"


def test_search_triggered_calls_commit_callback(tmp_path: Path):
    calls: list[int] = []
    _run(tmp_path, custom_keywords=("比特币",), on_search_committed=lambda: calls.append(1))
    assert calls == [1]


def test_skip_search_does_not_call_commit_callback(tmp_path: Path):
    """6 hot-board items all matching core keyword 'AI工具' meet the search gate,
    so skip_search is True and the commit callback must NOT fire."""
    calls: list[int] = []
    hot_board = [
        {
            "ClusterId": str(i),
            "Title": f"AI工具评测 {i}",
            "Url": f"https://www.toutiao.com/group/{i}/",
            "HotValue": 2_000_000,
            "QueryWord": "AI工具评测",
        }
        for i in range(1, 7)
    ]
    _run(tmp_path, custom_keywords=(), on_search_committed=lambda: calls.append(1),
         hot_board_data=hot_board)
    assert calls == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline_custom_keywords.py -v`
Expected: FAIL with `TypeError: run_toutiao_pipeline_v2() got an unexpected keyword argument 'custom_keywords'`

- [ ] **Step 3: 改 pipeline.py — 加导入**

In `src/heated_topics_v3/pipeline.py`, the top imports currently include:

```python
from heated_topics_v3.contracts import ItemDetail, MatchResult, UserProfile
```
Change to:
```python
from heated_topics_v3.contracts import ExtractedKeyword, ItemDetail, MatchResult, UserProfile
```

And the line:
```python
from heated_topics_v3.llm_keywords import extract_persona_keywords
```
Change to:
```python
from heated_topics_v3.llm_keywords import PersonaKeywordExtraction, extract_persona_keywords
```

Add a datetime import near the top of the file (after `import json`):
```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: 改 pipeline.py — 函数签名**

In `run_toutiao_pipeline_v2`, the signature currently ends with:
```python
    rendered_text_fetcher: Callable[[str, int], str] | None = None,
    llm_caller: Callable[..., str] | None = None,
) -> "ToutiaoV2Result":
```
Change to:
```python
    rendered_text_fetcher: Callable[[str, int], str] | None = None,
    llm_caller: Callable[..., str] | None = None,
    custom_keywords: tuple[str, ...] = (),
    on_search_committed: Callable[[], None] | None = None,
) -> "ToutiaoV2Result":
```

- [ ] **Step 5: 改 pipeline.py — custom 分支合成 extraction**

Currently (after the `profile = load_persona_profile(...)` / `effective_llm = ...` lines):
```python
    profile = load_persona_profile(profile_path)
    effective_llm = llm_caller or (lambda *a, **kw: call_llm(*a, cache_dir=llm_cache_root, **kw))
    extraction = extract_persona_keywords(
        profile,
        cache_dir=persona_keyword_cache_root,
        use_cache=True,
        llm=effective_llm,
        allow_llm=use_llm_keywords,
    )
```
Change to:
```python
    profile = load_persona_profile(profile_path)
    effective_llm = llm_caller or (lambda *a, **kw: call_llm(*a, cache_dir=llm_cache_root, **kw))
    if custom_keywords:
        extraction = PersonaKeywordExtraction(
            user_id=profile.user_id,
            persona_signature=profile.persona_signature,
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in custom_keywords),
            source="custom",
        )
    else:
        extraction = extract_persona_keywords(
            profile,
            cache_dir=persona_keyword_cache_root,
            use_cache=True,
            llm=effective_llm,
            allow_llm=use_llm_keywords,
        )
```

- [ ] **Step 6: 改 pipeline.py — persona_keywords 分支**

Currently:
```python
    keyword_phrases = tuple(k.keyword for k in extraction.keywords)

    persona_keywords = profile.core_keywords + keyword_phrases
```
Change to:
```python
    keyword_phrases = tuple(k.keyword for k in extraction.keywords)

    if custom_keywords:
        persona_keywords = keyword_phrases
    else:
        persona_keywords = profile.core_keywords + keyword_phrases
```

- [ ] **Step 7: 改 pipeline.py — 搜索成功回调**

Currently:
```python
    run_result = write_toutiao_run(
        user_id=profile.user_id,
        date=date,
        candidates=candidates,
        top_n=top_n,
        hot_board_snapshot=hot_board_snapshot,
        raw_search_by_keyword=enriched_search_by_keyword,
        raw_article_info_by_url=article_info_by_url,
        item_details=item_details,
        report_markdown=report_md,
        output_root=output_root,
        hot_board_cache_root=hot_board_cache_root,
    )
```
Immediately AFTER this block (before the `if summary_md is not None:` block), insert:
```python
    if on_search_committed is not None and not skip_search:
        on_search_committed()
```

Note: `skip_search` is the existing boolean computed earlier in the function. Firing on `not skip_search` after `write_toutiao_run` implements the "发起了搜索且流程走完才计数" rule.

- [ ] **Step 8: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline_custom_keywords.py -v`
Expected: PASS (6 passed)

- [ ] **Step 9: 跑既有 pipeline 测试确认无回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_toutiao_pipeline_v2.py -v`
Expected: PASS (all existing tests still pass — new params default to `()`/`None`)

- [ ] **Step 10: 提交**

```bash
git add src/heated_topics_v3/pipeline.py tests/test_pipeline_custom_keywords.py
git commit -m "feat: add custom_keywords replacement and search-committed callback to toutiao v2 pipeline"
```

---

## Task 3: CLI flag + 配额编排

**Files:**
- Modify: `src/heated_topics_v3/cli.py`
- Test: `tests/test_cli_quota.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_cli_quota.py`:

```python
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import heated_topics_v3.cli as cli
from heated_topics_v3.hot_board_cache import utc8_today

V2_PROFILE = {
    "user_id": "zhao_001",
    "level1": "科技AI",
    "level2": "AI工具应用",
    "personal": {
        "role": "AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习"],
        "value": "真实建议",
    },
    "core_keywords": ["AI工具"],
}


def _write_profile(tmp_path: Path) -> Path:
    path = tmp_path / "zhao_001.json"
    path.write_text(json.dumps(V2_PROFILE, ensure_ascii=False), encoding="utf-8")
    return path


def _fake_result(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=tmp_path / "run",
        report_path=tmp_path / "run" / "report.md",
        focused_path=tmp_path / "run" / "focused.json",
        kept_total=1,
        candidates_total=1,
        paths={"A": 1},
        hot_board_source="cache",
        keyword_source="custom",
    )


def test_cli_quota_exceeded_prints_message_exit_2(tmp_path, monkeypatch, capsys):
    profile_path = _write_profile(tmp_path)
    # Seed quota at the limit (3).
    quota_dir = tmp_path / "state" / "quota"
    quota_dir.mkdir(parents=True)
    (quota_dir / "zhao_001.json").write_text(
        json.dumps({"date": utc8_today(), "count": 3}), encoding="utf-8"
    )

    called = {"pipeline": False}

    def stub_pipeline(*_args, **_kwargs):
        called["pipeline"] = True
        return _fake_result(tmp_path)

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", stub_pipeline)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "toutiao", "--profile-v2", str(profile_path),
         "--state-root", str(tmp_path / "state"), "--no-llm"],
    )

    with pytest.raises(SystemExit) as exc:
        cli._main()
    assert exc.value.code == 2
    assert called["pipeline"] is False
    assert "今日额度已用完" in capsys.readouterr().err


def test_cli_skip_quota_bypasses_check(tmp_path, monkeypatch, capsys):
    profile_path = _write_profile(tmp_path)
    quota_dir = tmp_path / "state" / "quota"
    quota_dir.mkdir(parents=True)
    (quota_dir / "zhao_001.json").write_text(
        json.dumps({"date": utc8_today(), "count": 3}), encoding="utf-8"
    )

    captured = {}

    def stub_pipeline(*_args, **kwargs):
        captured.update(kwargs)
        return _fake_result(tmp_path)

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", stub_pipeline)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "toutiao", "--profile-v2", str(profile_path),
         "--state-root", str(tmp_path / "state"), "--skip-quota", "--no-llm"],
    )

    cli._main()
    # Pipeline ran despite quota being at the limit, and no commit callback wired.
    assert captured.get("on_search_committed") is None


def test_cli_custom_keyword_passed_to_pipeline(tmp_path, monkeypatch):
    profile_path = _write_profile(tmp_path)
    captured = {}

    def stub_pipeline(*_args, **kwargs):
        captured.update(kwargs)
        return _fake_result(tmp_path)

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", stub_pipeline)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "toutiao", "--profile-v2", str(profile_path),
         "--state-root", str(tmp_path / "state"), "--skip-quota", "--no-llm",
         "--custom-keyword", "比特币", "--custom-keyword", " ",
         "--custom-keyword", "美联储"],
    )

    cli._main()
    # Blank keyword is stripped out; order preserved.
    assert captured.get("custom_keywords") == ("比特币", "美联储")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_quota.py -v`
Expected: FAIL — `--custom-keyword`/`--state-root`/`--skip-quota` are unrecognized args (SystemExit 2 from argparse) or `custom_keywords` not passed.

- [ ] **Step 3: 改 cli.py — 加导入**

In `src/heated_topics_v3/cli.py`, after the existing `from heated_topics_v3.pipeline import (...)` block, add:

```python
from heated_topics_v3.hot_board_cache import utc8_today
from heated_topics_v3.profile_loader import load_persona_profile
from heated_topics_v3.quota import (
    QuotaExceededError,
    check_quota,
    commit_quota,
    load_quota,
)
```

- [ ] **Step 4: 改 cli.py — 新 flag**

In `_add_toutiao_args`, after the existing `parser.add_argument("--offline", action="store_true")` line, add:

```python
    parser.add_argument("--custom-keyword", dest="custom_keyword", action="append", default=[])
    parser.add_argument("--state-root", default=Path("state"), type=Path)
    parser.add_argument("--max-quota-per-day", dest="max_quota_per_day", default=3, type=int)
    parser.add_argument("--skip-quota", dest="skip_quota", action="store_true")
```

- [ ] **Step 5: 改 cli.py — 配额编排 + 传参**

In `_main`, the toutiao v2 branch currently reads:
```python
        if args.profile_v2 is not None:
            use_llm_keywords = args.llm_keywords and not args.no_llm
            use_llm_summary = args.llm_summary and not args.no_llm
            use_llm_rerank = args.llm_rerank and not args.no_llm
            result = run_toutiao_pipeline_v2(
                profile_path=args.profile_v2,
                output_root=args.output_root,
                fetched_at=fetched_at,
                hot_board_cache_root=args.cache_root,
                persona_keyword_cache_root=args.cache_root / "core_keywords",
                llm_cache_root=args.cache_root / "llm",
                use_llm_keywords=use_llm_keywords,
                use_llm_summary=use_llm_summary,
                use_llm_rerank=use_llm_rerank,
                force_hot_board_refresh=args.force_hot_board_refresh,
                offline=args.offline,
                top_n=args.top_n,
            )
```
Change to:
```python
        if args.profile_v2 is not None:
            use_llm_keywords = args.llm_keywords and not args.no_llm
            use_llm_summary = args.llm_summary and not args.no_llm
            use_llm_rerank = args.llm_rerank and not args.no_llm
            custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())
            today = utc8_today()
            on_search_committed = None
            if not args.skip_quota:
                user_id = load_persona_profile(args.profile_v2).user_id
                state = load_quota(args.state_root, user_id, today)
                try:
                    check_quota(state, args.max_quota_per_day)
                except QuotaExceededError as exc:
                    print(str(exc), file=sys.stderr)
                    raise SystemExit(2) from exc
                on_search_committed = lambda: commit_quota(args.state_root, user_id, today)
            result = run_toutiao_pipeline_v2(
                profile_path=args.profile_v2,
                output_root=args.output_root,
                fetched_at=fetched_at,
                hot_board_cache_root=args.cache_root,
                persona_keyword_cache_root=args.cache_root / "core_keywords",
                llm_cache_root=args.cache_root / "llm",
                use_llm_keywords=use_llm_keywords,
                use_llm_summary=use_llm_summary,
                use_llm_rerank=use_llm_rerank,
                force_hot_board_refresh=args.force_hot_board_refresh,
                offline=args.offline,
                top_n=args.top_n,
                custom_keywords=custom_keywords,
                on_search_committed=on_search_committed,
            )
```

Note: `main()` wraps `_main()` and only catches `(RuntimeError, ValueError)`; `SystemExit(2)` propagates untouched, giving the required exit code. A legacy profile makes `load_persona_profile` raise `ProfileSchemaError` (a `ValueError`), caught by `main()` → exit 1, matching existing behavior.

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_quota.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: 提交**

```bash
git add src/heated_topics_v3/cli.py tests/test_cli_quota.py
git commit -m "feat: wire daily quota and custom-keyword flags into toutiao CLI"
```

---

## Task 4: 配置 — .gitignore + README

**Files:**
- Modify: `.gitignore`
- Modify: 项目根 README（先确认文件名）

- [ ] **Step 1: 确认 README 文件名**

Run: `.venv/Scripts/python.exe -c "import glob; print(glob.glob('README*'))"`
Expected: 打印出实际 README 文件名（如 `['README.md']`）。后续步骤用该文件名。

- [ ] **Step 2: 忽略 state/**

In `.gitignore`, confirm whether `state/` is already ignored:

Run: `.venv/Scripts/python.exe -c "print('state/' in open('.gitignore', encoding='utf-8').read())"`

If it prints `False`, append a line `state/` to `.gitignore` (keep existing content untouched, add at end):

```
state/
```

- [ ] **Step 3: README 新增章节**

Append the following section to the README file (确认后的文件名):

```markdown
## 每日配额与自定义关键词（上线用法）

### 每日配额

每个用户每天最多获取热榜 `--max-quota-per-day` 次（默认 3）。第 N+1 次调用时，
后端在进入流程前拦截，向 stderr 打印 `今日额度已用完` 并以 exit code `2` 退出，
不产出任何结果目录。

- 配额状态存于 `state/quota/{user_id}.json`，格式 `{"date": "YYYY-MM-DD", "count": N}`。
- 跨天自动重置：读取时若 `date` 不是当天，`count` 视为 0。
- **计数语义**：只有「发起了搜索分支且流程完整走完」才 +1。若热榜命中已足够、
  直接走 Path A 直出（`skip_search`），不发起搜索，则不消耗配额。

### `--skip-quota`（前端集成必读）

本项目会被另一个项目集成。若由前端自行管理调用次数，请在每次调用时传
`--skip-quota`，后端将完全跳过配额检查与计数（不读写 `state/quota/`）。
不传该 flag 时，后端用自己的默认配额状态兜底，CLI 手动跑也会受同一份状态限制。

### 自定义关键词

传入 `--custom-keyword`（可重复）即用这些关键词**替换本次运行**的自动抽取关键词，
按输入顺序检索匹配；空白值会被过滤。`config/profiles/{user}.json` 里的
`core_keywords` 不受影响（仍是持久 persona，只是本次不参与）。本次运行的
`keyword_source` 会标记为 `custom`。

示例：

    python -m heated_topics_v3.cli toutiao --profile-v2 config/profiles/licai_001.json \
        --custom-keyword 比特币 --custom-keyword 美联储 --no-llm --top-n 10
```

- [ ] **Step 4: 提交**

```bash
git add .gitignore README.md
git commit -m "docs: document daily quota and custom-keyword usage"
```

---

## 全量回归

- [ ] **Step 1: 跑全套测试**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 全绿（131 既有 + 16 新增 = 147 passed）

---

## Self-Review 记录

- **Spec 覆盖**：配额（Task 1+3）、custom 替换（Task 2）、合成 extraction 不置空（Task 2 Step 5）、计数语义 `not skip_search`（Task 2 Step 7）、失败表场景 1/3/5/6/7（quota check exit 2 / skip_search 不计数 / 回调不阻断 / 空串过滤 / commit 写盘失败 swallow）、配置 state/gitignore/README（Task 4）——均有对应任务。
- **类型一致**：`QuotaState`/`QuotaExceededError`/`load_quota`/`check_quota`/`commit_quota` 签名在 Task 1 定义，Task 3 按同名调用；`PersonaKeywordExtraction`/`ExtractedKeyword` 字段与 `contracts.py`、`llm_keywords.py` 现有定义一致。
- **无占位符**：所有步骤含真实代码与命令。
```
