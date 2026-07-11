# V3 Clean Rebuild Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean the `V3` branch into a fresh V3-only project without changing the existing `v2` branch.

**Architecture:** Treat `v2` as the historical implementation branch and `V3` as a new clean project. Remove old V2 source, tests, reports, and historical planning files from the `V3` branch only. Recreate a compact project layout centered on user profiles, topic queries, platform hot-list providers, normalized hot items, topic clusters, and report/data outputs.

**Tech Stack:** Python, pytest, uv, standard library HTTP/JSON modules for the first pass.

## Branch Safety

- Current cleanup target branch: `V3`.
- Existing preserved branch: `v2`.
- Current observed `v2` commit before cleanup planning: `2d9cc652892139e0cccdc23460a4a50da440e53e`.
- Current observed `V3` commit before cleanup planning: `411a206bbe47c46c40165584213c184704b4dc54`.
- Cleanup must be committed only on `V3`.
- Do not run `git branch -D v2`, `git reset --hard v2`, or any command that moves the `v2` branch.
- Before deleting tracked files, verify `git branch --show-current` returns `V3`.

## Global Constraints

- Preserve `v2` untouched as the historical reference.
- Keep V3 project structure small and purpose-built.
- Keep user profile, query, hot item, topic cluster, report, and dataset contracts explicit.
- First batch platforms are `juejin`, `bilibili`, `baidu`.
- Second batch platforms are `weibo`, `toutiao`, `zhihu`.
- `xiaohongshu` is excluded because another project handles it.
- Do not commit local runtime outputs under `data/` or `reports/_archive/`.

---

## Target V3 Layout

Keep or create only this tracked layout:

```text
.env.example
.gitignore
README.md
pyproject.toml
uv.lock
config/
  profiles/
    tech_ai_creator.json
docs/
  decisions/
    v3-clean-rebuild.md
  specs/
    data-contract.md
    platform-hot-list-matrix.md
  plans/
    clean-rebuild.md
src/
  heated_topics_v3/
    __init__.py
    cli.py
    contracts.py
    profile_queries.py
    matching.py
    storage.py
    reporting.py
    providers/
      __init__.py
      juejin.py
      bilibili.py
      baidu.py
tests/
  test_contracts.py
  test_profile_queries.py
  test_matching.py
  test_storage.py
  providers/
    test_juejin.py
```

Optional later layout, not required in the cleanup commit:

```text
src/heated_topics_v3/providers/weibo.py
src/heated_topics_v3/providers/toutiao.py
src/heated_topics_v3/providers/zhihu.py
tests/providers/test_bilibili.py
tests/providers/test_baidu.py
```

## Files To Preserve From Current Branch

Preserve these tracked files if still useful:

- `.env.example`
- `.gitignore`
- `pyproject.toml`
- `uv.lock`

Rewrite these tracked files instead of preserving their current contents:

- `README.md`

Move or rewrite V3 docs into the new docs layout:

- Current `docs/superpowers/specs/2026-07-11-v3-platform-hot-list-matrix-design.md`
- Current `docs/superpowers/plans/2026-07-11-v3-platform-hot-list-matrix.md`
- Current `docs/superpowers/plans/2026-07-11-v3-clean-rebuild.md`

The rewritten docs should be concise and V3-only.

## Files And Directories To Remove From V3

Remove these from the `V3` branch:

- `CLAUDE.md`
- `README.v2.md`
- `reports/creator_topic_cards.md`
- `tools/run-demo.sh`
- All old `docs/2026-*` files.
- All old `docs/hot-topic-research-and-method-report.md`.
- All old `docs/v2-stage-report-2026-07-01.md`.
- All old `docs/superpowers/integrations/`.
- All old `docs/superpowers/specs/2026-06-*`.
- All old `docs/superpowers/specs/2026-07-07-*`.
- All old `docs/superpowers/plans/2026-06-*`.
- All old `docs/superpowers/plans/2026-07-07-*`.
- Entire old `src/core_pipeline/`.
- Entire old `src/search_discovery/`.
- Old top-level scripts under `src/`, including `collect_hot_records.py`, `demo_collect_hot_topics.py`, `demo_config.py`, `enrich_sources.py`, `fetch_hot_lists.py`, `generate_reports.py`, `hot_topic_types.py`, and `select_topics.py`.
- Entire old `src/browser/`.
- Old `tests/core_pipeline/`.
- Old `tests/search_discovery/`.
- Old top-level tests that target V2 modules.
- Old `config/search_discovery/`.

Do not remove untracked local `data/` and `reports/_archive/` through Git cleanup steps. They are local runtime artifacts and should stay untracked unless the user explicitly asks to delete them.

## New V3 Data Contracts

The clean project should define these first-class contracts in `src/heated_topics_v3/contracts.py`:

- `UserProfile`
- `TopicQuery`
- `HotItem`
- `HeatMetrics`
- `TopicCluster`
- `ReportBundle`

`TopicQuery` must exist even when a platform can collect hot lists without query input. In V3, queries carry profile intent into filtering, matching, scoring, and detail enrichment.

## Task 1: Verify Branch Safety

**Files:**
- No file changes.

**Interfaces:**
- Produces: command evidence that current branch is `V3`.
- Produces: command evidence that `v2` still points to its pre-cleanup commit.

- [ ] **Step 1: Confirm current branch**

Run:

```powershell
git branch --show-current
```

Expected output:

```text
V3
```

- [ ] **Step 2: Confirm v2 commit**

Run:

```powershell
git rev-parse v2
```

Expected output:

```text
2d9cc652892139e0cccdc23460a4a50da440e53e
```

- [ ] **Step 3: Confirm no tracked dirty changes block cleanup**

Run:

```powershell
git status --short --branch
```

Expected tracked state:

```text
## V3
```

Untracked `data/` and `reports/_archive/` may appear and should not block cleanup.

## Task 2: Remove V2 Tracked Files From V3

**Files:**
- Delete: old tracked V2 files and directories listed in "Files And Directories To Remove From V3".

**Interfaces:**
- Produces: a branch where old V2 code is no longer tracked on `V3`.

- [ ] **Step 1: Preview tracked files to be deleted**

Run:

```powershell
git ls-files
```

Expected: output includes old V2 files before deletion.

- [ ] **Step 2: Remove tracked old directories and files using Git**

Use `git rm` only on tracked files. Do not delete untracked runtime outputs.

Run:

```powershell
git rm -r CLAUDE.md README.v2.md reports/creator_topic_cards.md tools src tests config/search_discovery docs
```

Expected: Git stages deletions for old tracked files. This command also removes current V3 docs temporarily; Task 3 recreates the V3-only docs layout.

- [ ] **Step 3: Restore preserved tracked files if accidentally staged**

Run:

```powershell
git status --short
```

Expected: `.env.example`, `.gitignore`, `pyproject.toml`, and `uv.lock` are not deleted.

## Task 3: Create Clean V3 Project Skeleton

**Files:**
- Create: `README.md`
- Create: `config/profiles/tech_ai_creator.json`
- Create: `docs/decisions/v3-clean-rebuild.md`
- Create: `docs/specs/data-contract.md`
- Create: `docs/specs/platform-hot-list-matrix.md`
- Create: `docs/plans/clean-rebuild.md`
- Create: `src/heated_topics_v3/__init__.py`
- Create: `src/heated_topics_v3/contracts.py`
- Create: `src/heated_topics_v3/profile_queries.py`
- Create: `src/heated_topics_v3/providers/__init__.py`
- Create: `tests/test_contracts.py`
- Create: `tests/test_profile_queries.py`

**Interfaces:**
- Produces: clean import namespace `heated_topics_v3`.
- Produces: V3 data contracts.
- Produces: V3 profile-to-query generation tests.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_profile_queries.py` with:

```python
from heated_topics_v3.contracts import UserProfile
from heated_topics_v3.profile_queries import build_topic_queries


def test_profile_generates_queries_for_hot_list_filtering():
    profile = UserProfile(
        profile_id="tech_ai_creator",
        display_name="Tech AI Creator",
        domains=("tech", "ai"),
        audience=("developers",),
        content_modes=("tutorial", "analysis"),
        preferred_platforms=("juejin", "bilibili", "baidu"),
        core_keywords=("AI Agent", "MCP", "RAG"),
        entity_keywords=("OpenAI", "Claude Code"),
        excluded_keywords=("celebrity gossip",),
    )

    queries = build_topic_queries(profile)

    assert queries[0].query == "AI Agent MCP RAG"
    assert queries[0].usage == "filter_and_enrich_hot_lists"
    assert queries[1].query == "OpenAI Claude Code"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_profile_queries.py -q
```

Expected: FAIL because `heated_topics_v3` does not exist yet.

- [ ] **Step 3: Add minimal V3 contracts and query builder**

Create `src/heated_topics_v3/contracts.py` with dataclasses for `UserProfile` and `TopicQuery`. Create `src/heated_topics_v3/profile_queries.py` with `build_topic_queries(profile: UserProfile) -> list[TopicQuery]`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_profile_queries.py -q
```

Expected: PASS.

## Task 4: Commit Clean Rebuild Skeleton

**Files:**
- All staged cleanup and skeleton files.

**Interfaces:**
- Produces: one V3-only cleanup commit.

- [ ] **Step 1: Run verification**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest -q
```

Expected: all new V3 tests pass.

- [ ] **Step 2: Verify v2 branch pointer did not move**

Run:

```powershell
git rev-parse v2
```

Expected output:

```text
2d9cc652892139e0cccdc23460a4a50da440e53e
```

- [ ] **Step 3: Commit**

Run:

```powershell
git add -A
git commit -m "chore: clean rebuild V3 project"
```

Expected: commit is created on `V3`.

- [ ] **Step 4: Final branch safety check**

Run:

```powershell
git branch --show-current
git rev-parse v2
git log --oneline -1
```

Expected:

```text
V3
2d9cc652892139e0cccdc23460a4a50da440e53e
<new commit> chore: clean rebuild V3 project
```
