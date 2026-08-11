# OpenBiliClaw 多用户热点推荐 实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI that takes a `users.json` of multiple user profiles, fetches hot articles (with heat + body) from V3 providers, runs them through OpenBiliClaw's recommendation engine, and writes a per-user top-N `recommendations.json` with reason / topic_label / confidence.

**Architecture:** V3 providers (juejin / baidu_hot / zhihu_hot / zhihu_daily / toutiao) collect candidates; a new `serve_external_candidates()` method in OpenBiliClaw's `RecommendationEngine` ranks them; a thin HeatedTopics-side integration layer (5 modules under `heated_topics_v3.openbiliclaw_integration`) orchestrates per-user flow with `asyncio.Semaphore(5)` for concurrency. LLM via MiniMax-M2.7 (`openai_compatible`), embedding via Ollama `bge-m3`. Per-user isolation via per-user `data_dir` (Database, MemoryManager) — LLM / embedding services shared.

**Tech Stack:** Python 3.11+, HeatedTopics V3 (pyproject/uv), OpenBiliClaw v0.3.186+mur.1 (path dep from `../../openbiliclaw-sandbox`), httpx, pytest + pytest-asyncio, ruff, MiniMax OpenAI-compatible API, Ollama bge-m3.

**Spec:** `docs/superpowers/specs/2026-07-28-openbiliclaw-multi-user-recommender-design.md` (commit `f7b251c`)

**Worktree:** `E:\.code\My\heatedTopics\heatedTopics\.worktrees\openbiliclaw-multi-user-recommender\` (branch `feature/openbiliclaw-multi-user-recommender`, base `feature/baidu-zhihu-daily-mvp` @ `3cb4896`)

**OpenBiliClaw clone:** `E:\code\My\openbiliclaw-sandbox\` (its own git repo, branch `main`, HEAD `de11ea42`)

---

## File Structure

### New files in OpenBiliClaw sandbox (1 modified, 1 metadata)
- `src/openbiliclaw/recommendation/engine.py` — add `serve_external_candidates()` method
- `pyproject.toml` — bump version to `0.3.186+mur.1`

### New files in heatedTopics new worktree
```
src/heated_topics_v3/openbiliclaw_integration/
├── __init__.py
├── exceptions.py             # custom exception types
├── user_profile.py           # users.json → OnionProfile, per-user data_dir setup
├── candidate_adapter.py      # V3 Article → DiscoveredContent
├── output.py                 # Recommendation → JSON-serializable dict
├── recommender.py            # per-user orchestration, concurrency, error isolation
├── runtime.py                # LLM / embedding / engine construction
└── cli.py                    # argparse entry point

tests/openbiliclaw_integration/
├── __init__.py
├── conftest.py               # shared fixtures: tmp users.json, mock Article, etc.
├── test_user_profile.py
├── test_candidate_adapter.py
├── test_output.py
├── test_recommender.py
├── test_concurrency.py
├── test_cli.py
├── test_serve_external_patch.py
├── test_end_to_end_one_user.py
├── test_end_to_end_multi_user.py
├── test_acceptance_juejin.py            # pytest.mark.requires_llm + requires_ollama
├── test_acceptance_multi_user.py       # same markers
├── test_acceptance_degraded.py         # same markers
└── fixtures/
    ├── users_valid_3users.json
    ├── users_invalid_missing_user_id.json
    ├── users_invalid_empty_interests.json
    ├── articles_juejin_5.json
    ├── articles_zhihu_3.json
    ├── expected_output_1user.json
    ├── mock_soul_5layer.json
    └── mock_llm_responses.json

config/
└── openbiliclaw.toml.example

docs/
└── README-openbiliclaw-integration.md
```

### Modified files
- `pyproject.toml` (heatedTopics) — add `openbiliclaw = { path = "E:/code/My/openbiliclaw-sandbox" }` to dependencies (absolute path is required because the two repos live under different roots: `E:/.code/My/heatedTopics/...` vs `E:/code/My/...`; relative `../../openbiliclaw-sandbox` does not resolve)

---

## Phase 0: OpenBiliClaw Sandbox Patch

### Task 0.1: Add `serve_external_candidates` to RecommendationEngine

**Files:**
- Modify: `E:\code\My\openbiliclaw-sandbox\src\openbiliclaw\recommendation\engine.py` (insert after `serve_with_result` at line ~500, before `_mark_pool_shown_async`)
- Modify: `E:\code\My\openbiliclaw-sandbox\pyproject.toml` (bump version)

- [ ] **Step 1: Read the existing engine file to confirm insertion point**

Run: `sed -n '495,510p' "E:/code/My/openbiliclaw-sandbox/src/openbiliclaw/recommendation/engine.py"`
Expected: lines around `_mark_pool_shown_async` and `set_pool_inventory_commit_callback`.

- [ ] **Step 2: Insert the new method**

Open `E:\code\My\openbiliclaw-sandbox\src\openbiliclaw\recommendation\engine.py` and add the following method **immediately after the end of `serve_with_result`'s body** (i.e., right before `async def _mark_pool_shown_async`). The exact text to insert:

```python
    async def serve_external_candidates(
        self,
        profile: SoulProfile,
        candidates: list[DiscoveredContent],
        *,
        limit: int = 5,
        excluded_bvids: frozenset[str] = frozenset(),
        expression_mode: Literal["realtime", "precomputed"] = "realtime",
        persist: bool = True,
    ) -> list[Recommendation]:
        """Serve recommendations from an externally provided candidate list.

        Bypasses the SQLite pool read. Used by the heatedTopics integration
        layer, where V3 providers fetch candidates and we hand them directly
        to the engine. Filtering / curator / MMR / expression flow mirrors
        serve_with_result's post-snapshot path.

        Args:
            profile: User's soul profile for personalization.
            candidates: Pre-collected ``DiscoveredContent`` items (the
                integration layer builds these from V3 providers).
            limit: Maximum number of recommendations to return.
            excluded_bvids: Content IDs already shown (for pagination).
            expression_mode: ``"realtime"`` generates fresh expressions via
                LLM (slow, higher quality); ``"precomputed"`` uses
                ``pool_expression`` / ``pool_topic_label`` on each candidate
                (fast; requires upstream to have pre-populated these).
            persist: If True, insert recommendation rows into the per-user
                database (matches serve_with_result's side-effect). Disable
                for dry-run / one-shot CLI flows that don't need history.

        Returns:
            Up to ``limit`` ``Recommendation`` items.
        """
        if not candidates:
            return []
        async with self._serve_lock:
            if excluded_bvids:
                candidates = [c for c in candidates if c.bvid not in excluded_bvids]
            candidates = self._exclude_disliked_topic_candidates(candidates, profile)
            if not candidates:
                return []
            await self._merge_topic_supergroups(candidates)
            score_override, amplification_guard = await asyncio.to_thread(
                self._score_candidates_with_curator, candidates, None
            )
            embeddings = await self._fetch_candidate_embeddings(candidates)
            visual_bonus = await self._visual_bonus_map(candidates, profile)
            ranked, _, _ = await self._select_diversified_batch_with_timing_async(
                candidates,
                limit=limit,
                score_override=score_override,
                embeddings=embeddings,
                amplification_guard=amplification_guard,
                relevance_bonus=visual_bonus,
            )
            recommendations: list[Recommendation] = []
            for item in ranked:
                rec = Recommendation(
                    content=item,
                    confidence=item.relevance_score,
                    presented=False,
                )
                if expression_mode == "precomputed":
                    rec.expression = item.pool_expression.strip()
                    if not rec.expression:
                        rec.expression = self._fallback_expression(item)
                    rec.topic_label = item.pool_topic_label.strip()
                    if not rec.topic_label:
                        rec.topic_label = self._fallback_topic_label(profile)
                else:
                    rec.expression = ""
                    rec.topic_label = ""
                recommendations.append(rec)
            if persist and recommendations:
                rec_rows = [
                    {
                        "bvid": rec.content.bvid,
                        "item_key": rec.content.item_key,
                        "expression": rec.expression,
                        "topic": rec.topic_label,
                        "confidence": rec.confidence,
                        "presented": 0,
                    }
                    for rec in recommendations
                ]
                try:
                    ids = await asyncio.to_thread(
                        self._database.batch_insert_recommendations, rec_rows
                    )
                    for rec, rec_id in zip(recommendations, ids, strict=True):
                        rec.recommendation_id = rec_id
                except Exception:
                    logger.exception(
                        "serve_external_candidates: db persist failed; continuing without IDs"
                    )
            if expression_mode == "realtime":
                for rec, item in zip(recommendations, ranked, strict=True):
                    rec.expression, rec.topic_label = await self.generate_expression(
                        item, profile
                    )
                    if rec.recommendation_id:
                        try:
                            self._database.update_recommendation_content(
                                rec.recommendation_id,
                                expression=rec.expression,
                                topic=rec.topic_label,
                            )
                        except Exception:
                            logger.exception(
                                "serve_external_candidates: db update failed"
                            )
            return recommendations
```

- [ ] **Step 3: Bump pyproject.toml version**

Open `E:\code\My\openbiliclaw-sandbox\pyproject.toml`. Find `version = "0.3.185"`. Change to `version = "0.3.186+mur.1"`.

- [ ] **Step 4: Smoke test — verify the new method is importable**

Run:
```bash
cd E:/code/My/openbiliclaw-sandbox
python -c "from openbiliclaw.recommendation.engine import RecommendationEngine; assert hasattr(RecommendationEngine, 'serve_external_candidates'); print('OK')"
```
Expected output: `OK`

- [ ] **Step 5: Commit the patch in openbiliclaw-sandbox**

Run:
```bash
cd E:/code/My/openbiliclaw-sandbox
git add src/openbiliclaw/recommendation/engine.py pyproject.toml
git commit -m "feat(recommendation): add serve_external_candidates for external pool bypass (heatedTopics integration)"
```
Expected: 1 commit added. `git log -1 --oneline` shows the new commit.

---

## Phase 1: HeatedTopics Worktree Setup

### Task 1.1: Add openbiliclaw path dependency

**Files:**
- Modify: `E:\.code\My\heatedTopics\heatedTopics\.worktrees\openbiliclaw-multi-user-recommender\pyproject.toml`

- [ ] **Step 1: Read current pyproject.toml dependencies**

Run: `cat "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender/pyproject.toml" | sed -n '/\[project\]/,/\[tool/p'`
Expected: shows the `[project]` block with `dependencies = [...]`.

- [ ] **Step 2: Add the path dep to dependencies**

Open the `pyproject.toml`. In the `dependencies = [...]` list, add (alphabetically or at the end):

```toml
    "openbiliclaw",
```

But Python path dependencies use `tool.uv.sources` not the inline dict. Find or add a `[tool.uv.sources]` table. If it exists, add:
```toml
openbiliclaw = { path = "E:/code/My/openbiliclaw-sandbox" }
```

If `[tool.uv.sources]` doesn't exist, add it after the `[project]` block:
```toml
[tool.uv.sources]
openbiliclaw = { path = "E:/code/My/openbiliclaw-sandbox" }
```

Also ensure `"openbiliclaw"` is in `dependencies` list. The version constraint should be `>=0.3.186+mur.1,<0.4` so uv picks up the local 0.3.186+mur.1.

- [ ] **Step 3: Run `uv sync` and verify openbiliclaw installs from path**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv sync
```
Expected: `uv sync` succeeds, installs `openbiliclaw 0.3.186+mur.1` from the local path.

- [ ] **Step 4: Verify the path-dep import works in this worktree's env**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run python -c "from openbiliclaw.recommendation.engine import RecommendationEngine; print(hasattr(RecommendationEngine, 'serve_external_candidates'))"
```
Expected output: `True`

- [ ] **Step 5: Commit the pyproject change**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add pyproject.toml uv.lock
git commit -m "build: add openbiliclaw path dep (0.3.186+mur.1)"
```
Expected: 1 commit added.

### Task 1.2: Create empty package skeleton

**Files:**
- Create: `src/heated_topics_v3/openbiliclaw_integration/__init__.py`
- Create: `src/heated_topics_v3/openbiliclaw_integration/exceptions.py`
- Create: `tests/openbiliclaw_integration/__init__.py`
- Create: `tests/openbiliclaw_integration/conftest.py`

- [ ] **Step 1: Create the package `__init__.py`**

Create `E:\.code\My\heatedTopics\heatedTopics\.worktrees\openbiliclaw-multi-user-recommender\src\heated_topics_v3\openbiliclaw_integration\__init__.py` with:

```python
"""OpenBiliClaw multi-user hot-article recommender integration.

Bridges V3 providers (juejin / baidu_hot / zhihu_hot / zhihu_daily / toutiao)
to OpenBiliClaw's RecommendationEngine, accepting multiple user profiles
as JSON input and producing per-user top-N recommendations as JSON output.
"""

__all__ = [
    "exceptions",
    "user_profile",
    "candidate_adapter",
    "output",
    "recommender",
    "runtime",
    "cli",
]
```

- [ ] **Step 2: Create the exceptions module**

Create `src/heated_topics_v3/openbiliclaw_integration/exceptions.py` with:

```python
"""Custom exception types for the openbiliclaw_integration package."""


class IntegrationError(Exception):
    """Base exception for the integration layer."""


class ProfileValidationError(IntegrationError):
    """Raised when a user profile fails schema validation."""


class CandidateMappingError(IntegrationError):
    """Raised when a V3 Article cannot be mapped to DiscoveredContent."""


class UserPipelineError(IntegrationError):
    """Raised when per-user recommendation pipeline fails.

    Attributes:
        user_id: The user that failed.
        stage: Pipeline stage name (e.g. "fetch", "llm", "timeout").
    """

    def __init__(self, user_id: str, stage: str, message: str) -> None:
        self.user_id = user_id
        self.stage = stage
        super().__init__(f"[{user_id}/{stage}] {message}")


class ProviderFetchError(IntegrationError):
    """Raised when a V3 provider's fetch fails (network, parse, etc.)."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class LLMError(IntegrationError):
    """Raised when the LLM call times out or returns malformed output."""


class EmbeddingDegradedWarning(UserWarning):
    """Issued when embedding service is unavailable; MMR runs in degraded mode."""
```

- [ ] **Step 3: Create the test package `__init__.py`**

Create `tests/openbiliclaw_integration/__init__.py` with:

```python
"""Tests for the openbiliclaw_integration package."""
```

- [ ] **Step 4: Create the conftest.py**

Create `tests/openbiliclaw_integration/conftest.py` with:

```python
"""Shared pytest fixtures for openbiliclaw_integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def users_valid_3users() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "users_valid_3users.json").read_text(encoding="utf-8"))


@pytest.fixture
def tmp_users_path(tmp_path: Path, users_valid_3users: dict[str, Any]) -> Path:
    p = tmp_path / "users.json"
    p.write_text(json.dumps(users_valid_3users, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
```

- [ ] **Step 5: Verify package imports and tests can be collected**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run python -c "from heated_topics_v3.openbiliclaw_integration import exceptions; print('OK')"
uv run pytest tests/openbiliclaw_integration/ --collect-only -q
```
Expected first: `OK`. Second: collects 0 tests (no test files yet), no errors.

- [ ] **Step 6: Commit the package skeleton**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/ tests/openbiliclaw_integration/
git commit -m "feat(openbiliclaw_integration): scaffold package + exception types"
```

---

## Phase 2: user_profile module (TDD)

### Task 2.1: Create users.json fixtures

**Files:**
- Create: `tests/openbiliclaw_integration/fixtures/users_valid_3users.json`
- Create: `tests/openbiliclaw_integration/fixtures/users_invalid_missing_user_id.json`
- Create: `tests/openbiliclaw_integration/fixtures/users_invalid_empty_interests.json`
- Create: `tests/openbiliclaw_integration/fixtures/mock_soul_5layer.json`

- [ ] **Step 1: Create `users_valid_3users.json`**

Create `tests/openbiliclaw_integration/fixtures/users_valid_3users.json` with:

```json
{
  "users": [
    {
      "user_id": "u_security",
      "display_name": "网安研究生",
      "interests": [
        {"name": "零信任架构", "category": "网安", "weight": 0.9},
        {"name": "RAG 注入攻防", "category": "网安", "weight": 0.85},
        {"name": "Rust 系统编程", "category": "Rust", "weight": 0.7}
      ],
      "disliked_topics": ["娱乐八卦", "纯财经快讯"],
      "style": {"reading_depth": "deep", "tone_preference": "technical"},
      "context": {"primary_scene": "research", "device": "desktop"},
      "exploration_openness": 0.6,
      "favorite_up_users": ["白帽小a"],
      "source_platform_mix": {"juejin": 0.5, "zhihu": 0.3, "toutiao": 0.2},
      "core_traits": ["好奇心强", "系统化思考"],
      "deep_needs": ["理解底层原理"],
      "values": ["严谨", "开放"],
      "life_stage": "本科大四",
      "current_phase": "准备研究生方向",
      "cognitive_style": ["由表及里"],
      "recent_awareness": [
        {"date": "2026-07-20", "observation": "在看 RAG 注入攻防",
         "trend": "关注 LLM 安全", "emotion_guess": "兴奋"}
      ],
      "active_insights": [
        {"hypothesis": "用户偏好能拆到代码层的文章",
         "evidence": ["多次点赞带源码的文章"], "confidence": 0.7}
      ]
    },
    {
      "user_id": "u_rust",
      "display_name": "Rust 爱好者",
      "interests": [
        {"name": "Tokio 异步运行时", "category": "Rust", "weight": 0.95},
        {"name": "Axum Web 框架", "category": "Rust", "weight": 0.8}
      ],
      "disliked_topics": ["纯财经"],
      "style": {"reading_depth": "deep", "tone_preference": "technical"},
      "context": {"primary_scene": "coding", "device": "desktop"},
      "exploration_openness": 0.4,
      "favorite_up_users": [],
      "source_platform_mix": {"juejin": 0.7, "zhihu": 0.3},
      "core_traits": ["完美主义"],
      "deep_needs": ["写出可读代码"],
      "values": ["可读性", "性能"],
      "life_stage": "工作 3 年",
      "current_phase": "转型 Rust 后端",
      "cognitive_style": ["自底向上"]
    },
    {
      "user_id": "u_design",
      "display_name": "设计师",
      "interests": [
        {"name": "UI 排版原则", "category": "设计", "weight": 0.9},
        {"name": "字体设计", "category": "设计", "weight": 0.7}
      ],
      "disliked_topics": ["财经八卦"],
      "style": {"reading_depth": "medium", "tone_preference": "casual"},
      "context": {"primary_scene": "leisure", "device": "mobile"},
      "exploration_openness": 0.8,
      "favorite_up_users": [],
      "source_platform_mix": {"zhihu": 0.5, "baidu": 0.3, "toutiao": 0.2},
      "core_traits": ["审美驱动"],
      "deep_needs": ["美的东西"],
      "values": ["美", "少"],
      "life_stage": "自由职业",
      "current_phase": "接品牌项目"
    }
  ]
}
```

- [ ] **Step 2: Create `users_invalid_missing_user_id.json`**

Create `tests/openbiliclaw_integration/fixtures/users_invalid_missing_user_id.json` with:

```json
{
  "users": [
    {
      "display_name": "no id",
      "interests": [{"name": "x", "category": "x", "weight": 0.5}]
    }
  ]
}
```

- [ ] **Step 3: Create `users_invalid_empty_interests.json`**

Create `tests/openbiliclaw_integration/fixtures/users_invalid_empty_interests.json` with:

```json
{
  "users": [
    {
      "user_id": "u_empty",
      "display_name": "empty interests",
      "interests": []
    }
  ]
}
```

- [ ] **Step 4: Create `mock_soul_5layer.json`**

Create `tests/openbiliclaw_integration/fixtures/mock_soul_5layer.json` with:

```json
{
  "core": {
    "core_traits": ["好奇心强"],
    "deep_needs": ["理解底层原理"]
  },
  "values_layer": {
    "values": ["严谨", "开放"],
    "motivational_drivers": []
  },
  "interest": {
    "likes": [
      {"domain": "Rust", "weight": 0.9, "specifics": [{"name": "Tokio", "weight": 0.8}]}
    ],
    "dislikes": [],
    "favorite_up_users": []
  },
  "role": {
    "life_stage": "本科大四",
    "current_phase": "准备研究生方向"
  },
  "surface": {
    "cognitive_style": ["由表及里"],
    "exploration_openness": 0.6
  },
  "personality_portrait": "",
  "recent_awareness": [],
  "active_insights": [],
  "source_platform_mix": {"juejin": 0.5},
  "version": 2
}
```

- [ ] **Step 5: Verify fixtures parse as valid JSON**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run python -c "
import json
from pathlib import Path
for name in ['users_valid_3users', 'users_invalid_missing_user_id', 'users_invalid_empty_interests', 'mock_soul_5layer']:
    p = Path('tests/openbiliclaw_integration/fixtures') / f'{name}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    print(f'{name}: OK')
"
```
Expected: 4 lines each saying `OK`.

- [ ] **Step 6: Commit the fixtures**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add tests/openbiliclaw_integration/fixtures/
git commit -m "test(openbiliclaw_integration): add users.json + soul fixtures"
```

### Task 2.2: user_profile.load_users (TDD)

**Files:**
- Create: `src/heated_topics_v3/openbiliclaw_integration/user_profile.py`
- Test: `tests/openbiliclaw_integration/test_user_profile.py`

- [ ] **Step 1: Write the failing test for `load_users`**

Create `tests/openbiliclaw_integration/test_user_profile.py`:

```python
"""Tests for user_profile module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heated_topics_v3.openbiliclaw_integration import user_profile
from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError


def test_load_users_returns_list_of_user_specs(tmp_path: Path, users_valid_3users: dict) -> None:
    p = tmp_path / "users.json"
    p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    specs = user_profile.load_users(p)
    assert len(specs) == 3
    assert specs[0].user_id == "u_security"
    assert specs[1].interests[0].name == "Tokio 异步运行时"


def test_load_users_raises_on_missing_user_id(fixtures_dir: Path) -> None:
    p = fixtures_dir / "users_invalid_missing_user_id.json"
    with pytest.raises(ProfileValidationError) as exc:
        user_profile.load_users(p)
    assert "user_id" in str(exc.value).lower() or "u_" in str(exc.value)


def test_load_users_raises_on_empty_interests(fixtures_dir: Path) -> None:
    p = fixtures_dir / "users_invalid_empty_interests.json"
    with pytest.raises(ProfileValidationError) as exc:
        user_profile.load_users(p)
    assert "interests" in str(exc.value).lower()


def test_load_users_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        user_profile.load_users(tmp_path / "nope.json")


def test_load_users_raises_on_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json {{{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        user_profile.load_users(p)


def test_load_users_raises_on_missing_top_level_users_key(tmp_path: Path) -> None:
    p = tmp_path / "no_users.json"
    p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    with pytest.raises(ProfileValidationError) as exc:
        user_profile.load_users(p)
    assert "users" in str(exc.value).lower()


def test_user_spec_interest_weight_out_of_range_raises(tmp_path: Path) -> None:
    bad = {"users": [{"user_id": "x", "interests": [{"name": "a", "category": "a", "weight": 1.5}]}]}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ProfileValidationError):
        user_profile.load_users(p)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_user_profile.py -v
```
Expected: All tests FAIL with `ImportError: cannot import name 'user_profile'`.

- [ ] **Step 3: Implement `load_users` and `UserSpec`**

Create `src/heated_topics_v3/openbiliclaw_integration/user_profile.py`:

```python
"""Load users.json and build OpenBiliClaw profile objects.

Pipeline:
  load_users()   →  list[UserSpec]
  UserSpec       →  OnionProfile (via build_onion_profile())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openbiliclaw.soul.profile import (
    AwarenessNote,
    InsightHypothesis,
    InterestTag,
    OnionProfile,
    StylePreference,
    ContextMode,
)

from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError


@dataclass
class InterestSpec:
    name: str
    category: str
    weight: float


@dataclass
class StyleSpec:
    reading_depth: str = "medium"
    tone_preference: str = "neutral"


@dataclass
class ContextSpec:
    primary_scene: str = "general"
    device: str = "desktop"


@dataclass
class UserSpec:
    user_id: str
    display_name: str
    interests: list[InterestSpec]
    disliked_topics: list[str] = field(default_factory=list)
    style: StyleSpec = field(default_factory=StyleSpec)
    context: ContextSpec = field(default_factory=ContextSpec)
    exploration_openness: float = 0.5
    favorite_up_users: list[str] = field(default_factory=list)
    source_platform_mix: dict[str, float] = field(default_factory=dict)
    core_traits: list[str] = field(default_factory=list)
    deep_needs: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    life_stage: str = ""
    current_phase: str = ""
    cognitive_style: list[str] = field(default_factory=list)
    recent_awareness: list[dict[str, Any]] = field(default_factory=list)
    active_insights: list[dict[str, Any]] = field(default_factory=list)


def _parse_one_user(raw: dict[str, Any]) -> UserSpec:
    if "user_id" not in raw or not str(raw["user_id"]).strip():
        raise ProfileValidationError(f"user missing 'user_id': keys={list(raw.keys())}")
    interests_raw = raw.get("interests", [])
    if not interests_raw:
        raise ProfileValidationError(f"user {raw['user_id']!r} has empty 'interests'")
    interests: list[InterestSpec] = []
    for i, item in enumerate(interests_raw):
        if not isinstance(item, dict):
            raise ProfileValidationError(
                f"user {raw['user_id']!r} interest[{i}] not a dict: {item!r}"
            )
        weight = float(item.get("weight", 0.5))
        if not (0.0 <= weight <= 1.0):
            raise ProfileValidationError(
                f"user {raw['user_id']!r} interest[{i}].weight={weight} not in [0,1]"
            )
        interests.append(
            InterestSpec(
                name=str(item["name"]),
                category=str(item.get("category", item["name"])),
                weight=weight,
            )
        )
    style_raw = raw.get("style") or {}
    context_raw = raw.get("context") or {}
    return UserSpec(
        user_id=str(raw["user_id"]),
        display_name=str(raw.get("display_name", raw["user_id"])),
        interests=interests,
        disliked_topics=list(raw.get("disliked_topics", [])),
        style=StyleSpec(
            reading_depth=str(style_raw.get("reading_depth", "medium")),
            tone_preference=str(style_raw.get("tone_preference", "neutral")),
        ),
        context=ContextSpec(
            primary_scene=str(context_raw.get("primary_scene", "general")),
            device=str(context_raw.get("device", "desktop")),
        ),
        exploration_openness=float(raw.get("exploration_openness", 0.5)),
        favorite_up_users=list(raw.get("favorite_up_users", [])),
        source_platform_mix=dict(raw.get("source_platform_mix", {})),
        core_traits=list(raw.get("core_traits", [])),
        deep_needs=list(raw.get("deep_needs", [])),
        values=list(raw.get("values", [])),
        life_stage=str(raw.get("life_stage", "")),
        current_phase=str(raw.get("current_phase", "")),
        cognitive_style=list(raw.get("cognitive_style", [])),
        recent_awareness=list(raw.get("recent_awareness", [])),
        active_insights=list(raw.get("active_insights", [])),
    )


def load_users(path: str | Path) -> list[UserSpec]:
    """Load and validate users.json. Raises on any error.

    Raises:
        FileNotFoundError: file does not exist
        json.JSONDecodeError: file is not valid JSON
        ProfileValidationError: schema invalid
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"users.json not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "users" not in raw:
        raise ProfileValidationError(
            f"top-level key 'users' missing in {p}; got keys={list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__}"
        )
    if not isinstance(raw["users"], list):
        raise ProfileValidationError(f"'users' must be a list in {p}")
    return [_parse_one_user(item) for item in raw["users"]]


def build_onion_profile(spec: UserSpec) -> OnionProfile:
    """Build an OpenBiliClaw OnionProfile from a UserSpec.

    Uses populate_from_flat_preference() for the preference layer; assigns
    onion layers directly; passes awareness/insight through from_dict.
    """
    preference_data: dict[str, Any] = {
        "interests": [
            {
                "name": i.name,
                "category": i.category,
                "weight": i.weight,
            }
            for i in spec.interests
        ],
        "disliked_topics": list(spec.disliked_topics),
        "exploration_openness": spec.exploration_openness,
        "favorite_up_users": list(spec.favorite_up_users),
        "source_platform_mix": dict(spec.source_platform_mix),
        "style": {
            "reading_depth": spec.style.reading_depth,
            "tone_preference": spec.style.tone_preference,
        },
        "context": {
            "primary_scene": spec.context.primary_scene,
            "device": spec.context.device,
        },
    }
    soul_dict: dict[str, Any] = {
        "core": {
            "core_traits": list(spec.core_traits),
            "deep_needs": list(spec.deep_needs),
        },
        "values_layer": {
            "values": list(spec.values),
            "motivational_drivers": [],
        },
        "interest": {
            "likes": [],
            "dislikes": [],
            "favorite_up_users": list(spec.favorite_up_users),
        },
        "role": {
            "life_stage": spec.life_stage,
            "current_phase": spec.current_phase,
        },
        "surface": {
            "cognitive_style": list(spec.cognitive_style),
            "exploration_openness": spec.exploration_openness,
            "style": {
                "reading_depth": spec.style.reading_depth,
                "tone_preference": spec.style.tone_preference,
            },
            "context": {
                "primary_scene": spec.context.primary_scene,
                "device": spec.context.device,
            },
        },
        "personality_portrait": "",
        "recent_awareness": list(spec.recent_awareness),
        "active_insights": list(spec.active_insights),
        "source_platform_mix": dict(spec.source_platform_mix),
        "version": 2,
    }
    profile = OnionProfile.from_dict(soul_dict)
    profile.populate_from_flat_preference(preference_data)
    return profile


def user_data_dir(base_dir: str | Path, user_id: str) -> Path:
    """Return the per-user data directory, creating it on demand."""
    safe_user_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_id)
    p = Path(base_dir) / "users" / safe_user_id
    p.mkdir(parents=True, exist_ok=True)
    return p
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_user_profile.py -v
```
Expected: All tests PASS.

- [ ] **Step 5: Add tests for `build_onion_profile`**

Append to `tests/openbiliclaw_integration/test_user_profile.py`:

```python
def test_build_onion_profile_populates_layers(tmp_path: Path, users_valid_3users: dict) -> None:
    p = tmp_path / "users.json"
    p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    specs = user_profile.load_users(p)
    profile = user_profile.build_onion_profile(specs[0])
    assert profile.life_stage == "本科大四"
    assert "好奇心强" in profile.core.core_traits
    assert len(profile.recent_awareness) == 1
    assert profile.recent_awareness[0].observation == "在看 RAG 注入攻防"
    assert profile.preferences.disliked_topics == ["娱乐八卦", "纯财经快讯"]
    assert profile.surface.exploration_openness == pytest.approx(0.6)


def test_user_data_dir_creates_directory(tmp_path: Path) -> None:
    d = user_profile.user_data_dir(tmp_path, "u_security/with/slash")
    assert d.is_dir()
    assert d.parent.name == "users"
    # Slashes converted to underscores
    assert "_" in d.name or d.name == "u_security_with_slash"


def test_user_data_dir_idempotent(tmp_path: Path) -> None:
    d1 = user_profile.user_data_dir(tmp_path, "u_a")
    d2 = user_profile.user_data_dir(tmp_path, "u_a")
    assert d1 == d2
```

- [ ] **Step 6: Run the new tests**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_user_profile.py -v
```
Expected: All tests PASS.

- [ ] **Step 7: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/user_profile.py tests/openbiliclaw_integration/test_user_profile.py
git commit -m "feat(openbiliclaw_integration): user_profile loader + OnionProfile builder"
```

---

## Phase 3: candidate_adapter module (TDD)

### Task 3.1: Add article fixtures

**Files:**
- Create: `tests/openbiliclaw_integration/fixtures/articles_juejin_5.json`
- Create: `tests/openbiliclaw_integration/fixtures/articles_zhihu_3.json`

- [ ] **Step 1: Create `articles_juejin_5.json`**

Create `tests/openbiliclaw_integration/fixtures/articles_juejin_5.json` with:

```json
{
  "platform": "juejin",
  "articles": [
    {
      "article_id": "712345",
      "title": "用 Tokio 实现零信任网关：源码级拆解",
      "url": "https://juejin.cn/post/712345",
      "author": "rustacean_daily",
      "body_text": "本文从零开始拆解一个基于 Tokio 的零信任网关实现...",
      "published_at": "2026-07-25T10:00:00Z",
      "tags": ["Rust", "Tokio", "网安"],
      "heat": {"view": 12345, "like": 234, "comment": 56, "rank": 3}
    },
    {
      "article_id": "712346",
      "title": "Rust 异步运行时对比：Tokio vs async-std",
      "url": "https://juejin.cn/post/712346",
      "author": "async_explorer",
      "body_text": "两个 runtime 的设计哲学差异...",
      "published_at": "2026-07-24T08:00:00Z",
      "tags": ["Rust", "async"],
      "heat": {"view": 8901, "like": 156, "comment": 32, "rank": 5}
    },
    {
      "article_id": "712347",
      "title": "财经快讯：本周市场热点",
      "url": "https://juejin.cn/post/712347",
      "author": "finance_bot",
      "body_text": "本周市场热点摘要...",
      "published_at": "2026-07-26T03:00:00Z",
      "tags": ["财经"],
      "heat": {"view": 50230, "like": 100, "comment": 200, "rank": 1}
    },
    {
      "article_id": "712348",
      "title": "TypeScript 5.4 新特性",
      "url": "https://juejin.cn/post/712348",
      "author": "ts_news",
      "body_text": "TypeScript 5.4 引入的新语法...",
      "published_at": "2026-07-26T12:00:00Z",
      "tags": ["TypeScript"],
      "heat": {"view": 6700, "like": 89, "comment": 12, "rank": 8}
    },
    {
      "article_id": "712349",
      "title": "娱乐八卦：本周热搜",
      "url": "https://juejin.cn/post/712349",
      "author": "gossip",
      "body_text": "本周娱乐圈热门...",
      "published_at": "2026-07-27T01:00:00Z",
      "tags": ["娱乐"],
      "heat": {"view": 99999, "like": 200, "comment": 500, "rank": 1}
    }
  ]
}
```

- [ ] **Step 2: Create `articles_zhihu_3.json`**

Create `tests/openbiliclaw_integration/fixtures/articles_zhihu_3.json` with:

```json
{
  "platform": "zhihu",
  "articles": [
    {
      "article_id": "q_987654",
      "title": "零信任架构在企业落地的 5 个坑",
      "url": "https://www.zhihu.com/question/987654",
      "author": "网安布道者",
      "body_text": "我们团队去年推零信任，踩了 5 个明显的坑...",
      "published_at": "2026-07-22T15:00:00Z",
      "tags": ["零信任", "网安", "企业"],
      "heat": {"view": 45000, "like": 1200, "comment": 380, "rank": 2}
    },
    {
      "article_id": "q_987655",
      "title": "Rust 在嵌入式开发中的现状",
      "url": "https://www.zhihu.com/question/987655",
      "author": "embedded_rust",
      "body_text": "Rust 在嵌入式领域已经有 5 年历史了...",
      "published_at": "2026-07-23T11:00:00Z",
      "tags": ["Rust", "嵌入式"],
      "heat": {"view": 12300, "like": 234, "comment": 67, "rank": 4}
    },
    {
      "article_id": "q_987656",
      "title": "RAG 系统的 7 种注入攻击",
      "url": "https://www.zhihu.com/question/987656",
      "author": "llm_security",
      "body_text": "RAG 系统的攻击面比想象的大...",
      "published_at": "2026-07-25T09:00:00Z",
      "tags": ["LLM", "网安", "RAG"],
      "heat": {"view": 38000, "like": 980, "comment": 250, "rank": 3}
    }
  ]
}
```

- [ ] **Step 3: Commit the article fixtures**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add tests/openbiliclaw_integration/fixtures/articles_juejin_5.json tests/openbiliclaw_integration/fixtures/articles_zhihu_3.json
git commit -m "test(openbiliclaw_integration): add article fixtures"
```

### Task 3.2: candidate_adapter.to_discovered (TDD)

**Files:**
- Create: `src/heated_topics_v3/openbiliclaw_integration/candidate_adapter.py`
- Test: `tests/openbiliclaw_integration/test_candidate_adapter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openbiliclaw_integration/test_candidate_adapter.py`:

```python
"""Tests for candidate_adapter module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from heated_topics_v3.openbiliclaw_integration import candidate_adapter


@pytest.fixture
def juejin_articles(fixtures_dir: Path) -> list[dict[str, Any]]:
    return json.loads((fixtures_dir / "articles_juejin_5.json").read_text(encoding="utf-8"))["articles"]


@pytest.fixture
def zhihu_articles(fixtures_dir: Path) -> list[dict[str, Any]]:
    return json.loads((fixtures_dir / "articles_zhihu_3.json").read_text(encoding="utf-8"))["articles"]


def test_to_discovered_maps_basic_fields(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert len(items) == 5
    first = items[0]
    assert first.title == "用 Tokio 实现零信任网关：源码级拆解"
    assert first.content_url == "https://juejin.cn/post/712345"
    assert first.source_platform == "juejin"
    assert first.content_id == "712345"
    assert first.content_type == "note"


def test_to_discovered_maps_heat_fields(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    first = items[0]
    assert first.view_count == 12345
    assert first.like_count == 234
    assert first.comment_count == 56
    assert first.source_rank == 3


def test_to_discovered_includes_body_text(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert "Tokio" in items[0].body_text
    assert "零信任" in items[0].body_text


def test_to_discovered_uses_platform_namespaced_item_key(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert items[0].item_key.startswith("juejin:")
    assert "712345" in items[0].item_key


def test_to_discovered_for_zhihu(zhihu_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(zhihu_articles, platform="zhihu")
    assert len(items) == 3
    assert items[0].content_id == "q_987654"
    assert items[0].source_platform == "zhihu"
    assert items[0].item_key.startswith("zhihu:")


def test_to_discovered_skips_articles_missing_required_fields() -> None:
    bad = [
        {"article_id": "1", "title": "ok", "url": "https://x.com/1", "body_text": "x"},
        {"title": "no id", "url": "https://x.com/2", "body_text": "x"},
        {"article_id": "3", "url": "https://x.com/3", "body_text": "x"},
        {"article_id": "4", "title": "no url", "body_text": "x"},
    ]
    items = candidate_adapter.to_discovered(bad, platform="juejin")
    assert len(items) == 1
    assert items[0].content_id == "1"


def test_to_discovered_preserves_tags(juejin_articles: list[dict]) -> None:
    items = candidate_adapter.to_discovered(juejin_articles, platform="juejin")
    assert "Rust" in items[0].tags
    assert "Tokio" in items[0].tags


def test_to_discovered_handles_missing_heat_field() -> None:
    articles = [
        {
            "article_id": "1",
            "title": "no heat",
            "url": "https://x.com/1",
            "body_text": "x",
        }
    ]
    items = candidate_adapter.to_discovered(articles, platform="juejin")
    assert items[0].view_count == 0
    assert items[0].like_count == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_candidate_adapter.py -v
```
Expected: All FAIL with `ImportError`.

- [ ] **Step 3: Implement `to_discovered`**

Create `src/heated_topics_v3/openbiliclaw_integration/candidate_adapter.py`:

```python
"""Map V3 Article dicts to OpenBiliClaw DiscoveredContent."""

from __future__ import annotations

from typing import Any

from openbiliclaw.discovery.engine import DiscoveredContent

from heated_topics_v3.openbiliclaw_integration.exceptions import CandidateMappingError


_REQUIRED_FIELDS = ("article_id", "title", "url", "body_text")


def to_discovered(
    articles: list[dict[str, Any]],
    *,
    platform: str,
) -> list[DiscoveredContent]:
    """Convert a list of V3 Article dicts to DiscoveredContent.

    Skips articles that lack required fields. Logs (does not raise) on
    individual skips; raises CandidateMappingError only if the input list
    is not a list.
    """
    if not isinstance(articles, list):
        raise CandidateMappingError(
            f"articles must be a list, got {type(articles).__name__}"
        )
    out: list[DiscoveredContent] = []
    for idx, raw in enumerate(articles):
        if not isinstance(raw, dict):
            continue
        missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            continue
        heat = raw.get("heat") or {}
        item = DiscoveredContent(
            title=str(raw["title"]),
            content_id=str(raw["article_id"]),
            content_url=str(raw["url"]),
            source_platform=platform,
            body_text=str(raw["body_text"]),
            description=str(raw.get("summary", raw.get("description", ""))),
            author_name=str(raw.get("author", "")),
            published_at=str(raw.get("published_at", "")),
            tags=list(raw.get("tags", [])),
            view_count=int(heat.get("view", 0)),
            like_count=int(heat.get("like", 0)),
            comment_count=int(heat.get("comment", 0)),
            favorite_count=int(heat.get("favorite", 0)),
            share_count=int(heat.get("share", 0)),
            source_rank=int(heat.get("rank", 0)),
            content_type="note",
        )
        out.append(item)
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_candidate_adapter.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/candidate_adapter.py tests/openbiliclaw_integration/test_candidate_adapter.py
git commit -m "feat(openbiliclaw_integration): candidate_adapter to_discovered"
```

---

## Phase 4: output module (TDD)

### Task 4.1: output.format_recommendation (TDD)

**Files:**
- Create: `src/heated_topics_v3/openbiliclaw_integration/output.py`
- Test: `tests/openbiliclaw_integration/test_output.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openbiliclaw_integration/test_output.py`:

```python
"""Tests for output module."""

from __future__ import annotations

from typing import Any

import pytest

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import output


def _make_recommendation(
    title: str = "T",
    url: str = "https://x.com/1",
    body_text: str = "body",
    view: int = 100,
    like: int = 10,
    comment: int = 2,
    rank: int = 1,
    topic_label: str = "topic",
    reason: str = "reason",
    confidence: float = 0.8,
) -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id="1",
        content_url=url,
        source_platform="juejin",
        body_text=body_text,
        content_type="note",
        view_count=view,
        like_count=like,
        comment_count=comment,
        source_rank=rank,
    )
    return Recommendation(
        content=item,
        expression=reason,
        topic_label=topic_label,
        confidence=confidence,
        presented=False,
    )


def test_format_recommendation_includes_all_fields() -> None:
    rec = _make_recommendation()
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["rank"] == 1
    assert d["title"] == "T"
    assert d["url"] == "https://x.com/1"
    assert d["source_platform"] == "juejin"
    assert d["heat"]["view"] == 100
    assert d["heat"]["like"] == 10
    assert d["heat"]["comment"] == 2
    assert d["heat"]["rank"] == 1
    assert d["topic_label"] == "topic"
    assert d["reason"] == "reason"
    assert d["confidence"] == pytest.approx(0.8)
    assert d["body_text_preview"] == "body"


def test_body_text_truncation_at_boundary() -> None:
    long = "x" * 1500
    rec = _make_recommendation(body_text=long)
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert len(d["body_text_preview"]) == 800
    assert d["body_text_length"] == 1500


def test_body_text_truncation_under_limit() -> None:
    rec = _make_recommendation(body_text="hello")
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["body_text_preview"] == "hello"
    assert d["body_text_length"] == 5


def test_body_text_truncation_exactly_at_limit() -> None:
    rec = _make_recommendation(body_text="x" * 800)
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["body_text_preview"] == "x" * 800
    assert d["body_text_length"] == 800


def test_format_recommendation_handles_missing_optional_fields() -> None:
    item = DiscoveredContent(
        title="t",
        content_id="1",
        content_url="u",
        source_platform="juejin",
    )
    rec = Recommendation(content=item, expression="", topic_label="", confidence=0.0, presented=False)
    d = output.format_recommendation(rec, rank=1, body_preview_chars=800)
    assert d["body_text_preview"] == ""
    assert d["body_text_length"] == 0
    assert d["heat"]["view"] == 0


def test_format_user_failure() -> None:
    d = output.format_user_failure(
        user_id="u_x",
        error_code="no_candidates",
        error_detail="all providers failed",
    )
    assert d["user_id"] == "u_x"
    assert d["error"] == "no_candidates"
    assert d["error_detail"] == "all providers failed"


def test_format_user_success_summary() -> None:
    d = output.format_user_success_summary(
        user_id="u_x",
        display_name="X",
        interests_count=2,
        disliked_count=1,
        fetched=100,
        after_filter=80,
        considered=80,
        embedding_degraded=False,
    )
    assert d["user_id"] == "u_x"
    assert d["display_name"] == "X"
    assert d["input_profile_summary"]["interests_count"] == 2
    assert d["pipeline"]["candidates_fetched"] == 100
    assert d["pipeline"]["candidates_considered_by_engine"] == 80
    assert d["pipeline"]["embedding_degraded"] is False


def test_full_envelope() -> None:
    rec = _make_recommendation()
    user = output.format_user_success_summary(
        "u_x", "X", 1, 0, 10, 10, 10, False
    )
    user["recommendations"] = [
        output.format_recommendation(rec, rank=1, body_preview_chars=800)
    ]
    env = output.build_envelope(
        users=[user],
        llm_model="MiniMax-M2.7",
        embedding_model="bge-m3",
        config_version="0.3.186+mur.1",
    )
    assert "generated_at" in env
    assert env["llm_model"] == "MiniMax-M2.7"
    assert env["config_version"] == "0.3.186+mur.1"
    assert len(env["users"]) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_output.py -v
```
Expected: All FAIL with `ImportError`.

- [ ] **Step 3: Implement output.py**

Create `src/heated_topics_v3/openbiliclaw_integration/output.py`:

```python
"""Format recommendations into the JSON output schema."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from openbiliclaw.recommendation.engine import Recommendation


def _truncate(s: str, max_chars: int) -> str:
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[:max_chars]


def format_recommendation(
    rec: Recommendation,
    *,
    rank: int,
    body_preview_chars: int,
) -> dict[str, Any]:
    """Convert one Recommendation to its output dict shape."""
    item = rec.content
    return {
        "rank": rank,
        "title": item.title,
        "url": item.content_url,
        "source_platform": item.source_platform,
        "heat": {
            "view": int(item.view_count),
            "like": int(item.like_count),
            "comment": int(item.comment_count),
            "favorite": int(item.favorite_count),
            "share": int(item.share_count),
            "rank": int(item.source_rank),
        },
        "body_text_preview": _truncate(item.body_text or "", body_preview_chars),
        "body_text_length": len(item.body_text or ""),
        "topic_label": rec.topic_label or "",
        "reason": rec.expression or "",
        "confidence": float(rec.confidence),
        "published_at": item.published_at or "",
    }


def format_user_failure(
    *,
    user_id: str,
    error_code: str,
    error_detail: str,
) -> dict[str, Any]:
    """Format a failed user entry for the output JSON."""
    return {
        "user_id": user_id,
        "error": error_code,
        "error_detail": error_detail,
    }


def format_user_success_summary(
    *,
    user_id: str,
    display_name: str,
    interests_count: int,
    disliked_count: int,
    fetched: int,
    after_filter: int,
    considered: int,
    embedding_degraded: bool,
) -> dict[str, Any]:
    """Format the per-user envelope (recommendations added separately)."""
    return {
        "user_id": user_id,
        "display_name": display_name,
        "input_profile_summary": {
            "interests_count": interests_count,
            "disliked_count": disliked_count,
        },
        "pipeline": {
            "candidates_fetched": fetched,
            "candidates_after_filter": after_filter,
            "candidates_considered_by_engine": considered,
            "embedding_degraded": embedding_degraded,
        },
        "recommendations": [],
    }


def build_envelope(
    *,
    users: list[dict[str, Any]],
    llm_model: str,
    embedding_model: str,
    config_version: str,
) -> dict[str, Any]:
    """Build the top-level output JSON."""
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_version": config_version,
        "llm_model": llm_model,
        "embedding_model": embedding_model,
        "users": users,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_output.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/output.py tests/openbiliclaw_integration/test_output.py
git commit -m "feat(openbiliclaw_integration): output formatter for recommendations + envelope"
```

---

## Phase 5: runtime module (OpenBiliClaw service setup)

### Task 5.1: runtime.build_recommender (TDD)

**Files:**
- Create: `src/heated_topics_v3/openbiliclaw_integration/runtime.py`
- Test: `tests/openbiliclaw_integration/test_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openbiliclaw_integration/test_runtime.py`:

```python
"""Tests for runtime module (OpenBiliClaw service construction)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


def test_load_openbiliclaw_config_reads_path(tmp_path: Path) -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime
    cfg_path = tmp_path / "obc.toml"
    cfg_path.write_text(
        "[llm]\nprovider_type = 'openai_compatible'\nbase_url = 'https://x'\nmodel = 'm'\n\n"
        "[embedding]\nprovider = 'ollama'\nmodel = 'bge-m3'\n",
        encoding="utf-8",
    )
    cfg = runtime.load_openbiliclaw_config(cfg_path)
    assert cfg is not None


def test_load_openbiliclaw_config_returns_none_on_missing(tmp_path: Path) -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime
    assert runtime.load_openbiliclaw_config(tmp_path / "nope.toml") is None


def test_verify_patch_present() -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime
    runtime.verify_patch()  # should not raise
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_runtime.py -v
```
Expected: All FAIL with `ImportError`.

- [ ] **Step 3: Implement runtime.py (basic config + verify_patch)**

Create `src/heated_topics_v3/openbiliclaw_integration/runtime.py`:

```python
"""OpenBiliClaw runtime construction (LLM, embedding, per-user engine)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_openbiliclaw_config(path: str | Path) -> Any | None:
    """Load an OpenBiliClaw config.toml. Returns None on missing file.

    We use OpenBiliClaw's own config loader; falls back gracefully when
    not available so unit tests don't need the real config.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        from openbiliclaw.config import load_config  # type: ignore
        return load_config(p)
    except Exception as exc:
        logger.warning("Failed to load OpenBiliClaw config from %s: %s", p, exc)
        return None


def verify_patch() -> None:
    """Verify the OpenBiliClaw patch (serve_external_candidates) is present.

    Raises RuntimeError with a clear message if the patch is missing.
    """
    try:
        from openbiliclaw.recommendation.engine import RecommendationEngine
    except Exception as exc:
        raise RuntimeError(
            f"Cannot import openbiliclaw.recommendation.engine: {exc}. "
            f"Make sure openbiliclaw-sandbox is cloned and the path dep is installed."
        ) from exc
    if not hasattr(RecommendationEngine, "serve_external_candidates"):
        raise RuntimeError(
            "OpenBiliClaw patch missing: RecommendationEngine has no "
            "'serve_external_candidates' method. Re-apply the patch in "
            "openbiliclaw-sandbox (commit 'feat(recommendation): add "
            "serve_external_candidates...')."
        )


def check_env() -> list[str]:
    """Check required environment variables. Returns list of missing names."""
    missing: list[str] = []
    if not os.environ.get("OPENBILICLAW_LLM_API_KEY"):
        missing.append("OPENBILICLAW_LLM_API_KEY")
    return missing


def check_ollama(base_url: str = "http://127.0.0.1:11434") -> tuple[bool, str]:
    """Check that Ollama is reachable. Returns (ok, message)."""
    import httpx
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False, f"Ollama at {base_url} returned {r.status_code}"
        tags = r.json().get("models", [])
        names = {t.get("name", "").split(":")[0] for t in tags}
        if "bge-m3" not in names:
            return False, f"Ollama at {base_url} has no 'bge-m3' model; run `ollama pull bge-m3`"
        return True, "ok"
    except Exception as exc:
        return False, f"Ollama at {base_url} unreachable: {exc}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_runtime.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/runtime.py tests/openbiliclaw_integration/test_runtime.py
git commit -m "feat(openbiliclaw_integration): runtime config + patch verification"
```

---

## Phase 6: recommender module (per-user orchestration, TDD)

### Task 6.1: recommender.run_one_user with mocked engine

**Files:**
- Modify: `src/heated_topics_v3/openbiliclaw_integration/recommender.py` (create)
- Test: `tests/openbiliclaw_integration/test_recommender.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/openbiliclaw_integration/test_recommender.py`:

```python
"""Tests for recommender orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation
from openbiliclaw.soul.profile import OnionProfile

from heated_topics_v3.openbiliclaw_integration import recommender


def _mock_article(article_id: str = "1", title: str = "T", platform: str = "juejin") -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": title,
        "url": f"https://{platform}.com/{article_id}",
        "body_text": "body",
        "author": "a",
        "heat": {"view": 100, "like": 10, "comment": 1, "rank": 1},
        "tags": [],
    }


def _mock_recommendation(
    title: str = "T", topic: str = "tp", reason: str = "r", confidence: float = 0.8
) -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id="1",
        content_url="https://x.com/1",
        source_platform="juejin",
        body_text="body",
        content_type="note",
    )
    return Recommendation(
        content=item, expression=reason, topic_label=topic,
        confidence=confidence, presented=False,
    )


def test_run_one_user_returns_recommendations(tmp_path: Path, users_valid_3users: dict) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")

    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )

    with patch.object(recommender, "build_recommender", return_value=mock_engine), \
         patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
        )
    assert result["user_id"] == spec.user_id
    assert "recommendations" in result
    assert len(result["recommendations"]) == 1
    assert result["pipeline"]["candidates_fetched"] == 1


def test_run_one_user_handles_no_candidates(tmp_path: Path, users_valid_3users: dict) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(return_value=[])

    with patch.object(recommender, "build_recommender", return_value=mock_engine), \
         patch.object(recommender, "fetch_candidates", return_value=[]):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)
    assert "error" in result
    assert result["error"] == "no_candidates"


def test_run_one_user_timeout_returns_error(tmp_path: Path, users_valid_3users: dict) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(side_effect=TimeoutError)

    with patch.object(recommender, "build_recommender", return_value=mock_engine), \
         patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(
            spec, data_dir=tmp_path / "runtime", limit=5, per_user_timeout=0.1
        )
    assert "error" in result


def test_run_one_user_isolated_engine_per_user(tmp_path: Path, users_valid_3users: dict) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    engines = []
    def fake_build_recommender(spec, data_dir, **kwargs):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[_mock_recommendation()])
        engines.append((spec.user_id, data_dir))
        return eng
    with patch.object(recommender, "build_recommender", side_effect=fake_build_recommender), \
         patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]):
        for spec in recommender.load_users(users_p):
            recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)
    assert len(engines) == 3
    # Each user gets a distinct data_dir
    assert len({d for _, d in engines}) == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_recommender.py -v
```
Expected: All FAIL with `ImportError`.

- [ ] **Step 3: Implement `recommender.py` (skeleton) with `load_users` re-export and `build_recommender` stub**

Create `src/heated_topics_v3/openbiliclaw_integration/recommender.py`:

```python
"""Per-user recommendation orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from heated_topics_v3.openbiliclaw_integration import candidate_adapter, output, user_profile
from heated_topics_v3.openbiliclaw_integration.exceptions import UserPipelineError

logger = logging.getLogger(__name__)


# Re-export for convenience so tests can patch via `recommender.load_users`.
load_users = user_profile.load_users


# Stubs — real implementation in Task 6.2.
def fetch_candidates(
    spec: user_profile.UserSpec,
    *,
    providers: list[str] | None = None,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch articles for one user from the configured V3 providers.

    Real implementation invokes V3 provider modules. For tests, this is
    mocked.
    """
    return []


def build_recommender(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    shared_runtime: Any | None = None,
    persist: bool = False,
) -> Any:
    """Build (or fetch) a per-user RecommendationEngine.

    Real implementation wires LLM / embedding / database. For tests, this
    is mocked.
    """
    raise NotImplementedError("build_recommender must be patched in tests")


async def _run_one_user_async(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int,
    body_preview_chars: int,
    per_user_timeout: float,
    providers: list[str] | None,
    shared_runtime: Any | None,
) -> dict[str, Any]:
    """Async body of run_one_user."""
    articles = fetch_candidates(spec, providers=providers)
    if not articles:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="no_candidates",
            error_detail=f"Fetched 0 articles from providers={providers or 'all'}",
        )
    candidates = candidate_adapter.to_discovered(articles, platform=articles[0].get("platform", "juejin") if isinstance(articles[0], dict) and "platform" in articles[0] else "juejin")
    # If articles don't carry 'platform' per-item, attribute by provider list order.
    if not any(isinstance(a, dict) and "platform" in a for a in articles):
        if providers and len(providers) == 1:
            candidates = candidate_adapter.to_discovered(articles, platform=providers[0])
    profile = user_profile.build_onion_profile(spec)
    engine = build_recommender(
        spec, data_dir=data_dir, shared_runtime=shared_runtime, persist=True
    )
    try:
        async with asyncio.timeout(per_user_timeout):
            recommendations = await engine.serve_external_candidates(
                profile, candidates, limit=limit
            )
    except TimeoutError:
        return output.format_user_failure(
            user_id=spec.user_id, error_code="timeout",
            error_detail=f"exceeded {per_user_timeout}s",
        )
    except Exception as exc:
        logger.exception("user %s: engine failed", spec.user_id)
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="engine_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    if not recommendations:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="no_recommendations",
            error_detail="Engine returned 0 recommendations",
        )
    rec_dicts = [
        output.format_recommendation(rec, rank=i + 1, body_preview_chars=body_preview_chars)
        for i, rec in enumerate(recommendations)
    ]
    user_summary = output.format_user_success_summary(
        user_id=spec.user_id,
        display_name=spec.display_name,
        interests_count=len(spec.interests),
        disliked_count=len(spec.disliked_topics),
        fetched=len(articles),
        after_filter=len(candidates),
        considered=len(candidates),
        embedding_degraded=False,
    )
    user_summary["recommendations"] = rec_dicts
    return user_summary


def run_one_user(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int = 5,
    body_preview_chars: int = 800,
    per_user_timeout: float = 60.0,
    providers: list[str] | None = None,
    shared_runtime: Any | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper around _run_one_user_async."""
    return asyncio.run(
        _run_one_user_async(
            spec,
            data_dir=data_dir,
            limit=limit,
            body_preview_chars=body_preview_chars,
            per_user_timeout=per_user_timeout,
            providers=providers,
            shared_runtime=shared_runtime,
        )
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_recommender.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/recommender.py tests/openbiliclaw_integration/test_recommender.py
git commit -m "feat(openbiliclaw_integration): per-user recommender orchestration (mocked engine)"
```

---

## Phase 7: Multi-user concurrency (TDD)

### Task 7.1: run_all_users with semaphore

**Files:**
- Modify: `src/heated_topics_v3/openbiliclaw_integration/recommender.py`
- Test: `tests/openbiliclaw_integration/test_concurrency.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openbiliclaw_integration/test_concurrency.py`:

```python
"""Tests for multi-user concurrent orchestration."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heated_topics_v3.openbiliclaw_integration import recommender


def _users(n: int) -> list[dict[str, Any]]:
    return {
        "users": [
            {
                "user_id": f"u{i}",
                "display_name": f"U{i}",
                "interests": [{"name": "x", "category": "x", "weight": 0.5}],
            }
            for i in range(n)
        ]
    }


@pytest.mark.asyncio
async def test_run_all_users_serial_default(tmp_path: Path) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(_users(3), ensure_ascii=False), encoding="utf-8")
    with patch.object(
        recommender, "_run_one_user_async",
        new_callable=AsyncMock,
        side_effect=[
            {"user_id": "u0", "recommendations": []},
            {"user_id": "u1", "recommendations": []},
            {"user_id": "u2", "recommendations": []},
        ],
    ):
        results = await recommender.run_all_users(
            users_path=users_p, data_dir=tmp_path, max_parallel=1
        )
    assert len(results) == 3
    assert [r["user_id"] for r in results] == ["u0", "u1", "u2"]


@pytest.mark.asyncio
async def test_run_all_users_parallel_respects_cap(tmp_path: Path) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(_users(10), ensure_ascii=False), encoding="utf-8")

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_run(spec, **kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return {"user_id": spec.user_id, "recommendations": []}

    with patch.object(
        recommender, "_run_one_user_async",
        new_callable=AsyncMock, side_effect=fake_run,
    ):
        results = await recommender.run_all_users(
            users_path=users_p, data_dir=tmp_path, max_parallel=3
        )
    assert len(results) == 10
    assert max_active <= 3
    assert max_active >= 2  # actually parallel


@pytest.mark.asyncio
async def test_run_all_users_isolates_failures(tmp_path: Path) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(_users(3), ensure_ascii=False), encoding="utf-8")

    async def fake_run(spec, **kwargs):
        if spec.user_id == "u1":
            return {"user_id": "u1", "error": "boom"}
        return {"user_id": spec.user_id, "recommendations": []}

    with patch.object(
        recommender, "_run_one_user_async",
        new_callable=AsyncMock, side_effect=fake_run,
    ):
        results = await recommender.run_all_users(
            users_path=users_p, data_dir=tmp_path, max_parallel=2
        )
    assert len(results) == 3
    assert any(r.get("error") == "boom" for r in results)
    assert sum(1 for r in results if "error" not in r) == 2
```

- [ ] **Step 2: Add `pytest-asyncio` to pyproject dev deps (if not present)**

Open `pyproject.toml`. Under `[project.optional-dependencies] dev = [...]`, ensure `pytest-asyncio>=0.24` is present. If not, add it.

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_concurrency.py -v
```
Expected: All FAIL with `AttributeError: module 'recommender' has no attribute 'run_all_users'`.

- [ ] **Step 4: Add `run_all_users` to recommender.py**

Append to `src/heated_topics_v3/openbiliclaw_integration/recommender.py`:

```python
async def run_all_users(
    *,
    users_path: Path,
    data_dir: Path,
    max_parallel: int = 5,
    limit: int = 5,
    body_preview_chars: int = 800,
    per_user_timeout: float = 60.0,
    providers: list[str] | None = None,
    shared_runtime: Any | None = None,
) -> list[dict[str, Any]]:
    """Run recommendation for all users with bounded concurrency.

    Per-user failures are isolated: one user's exception does not affect
    the others. Each user gets a separate data_dir under data_dir/users/.
    """
    specs = load_users(users_path)
    sem = asyncio.Semaphore(max_parallel)

    async def _one(spec: user_profile.UserSpec) -> dict[str, Any]:
        async with sem:
            user_data = user_profile.user_data_dir(data_dir, spec.user_id)
            try:
                return await _run_one_user_async(
                    spec,
                    data_dir=user_data,
                    limit=limit,
                    body_preview_chars=body_preview_chars,
                    per_user_timeout=per_user_timeout,
                    providers=providers,
                    shared_runtime=shared_runtime,
                )
            except Exception as exc:
                logger.exception("user %s unexpected error", spec.user_id)
                return output.format_user_failure(
                    user_id=spec.user_id,
                    error_code="internal",
                    error_detail=f"{type(exc).__name__}: {exc}",
                )

    return await asyncio.gather(*[_one(s) for s in specs])
```

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_concurrency.py -v
```
Expected: All PASS.

- [ ] **Step 6: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/recommender.py tests/openbiliclaw_integration/test_concurrency.py pyproject.toml uv.lock
git commit -m "feat(openbiliclaw_integration): bounded-concurrency run_all_users + pytest-asyncio"
```

---

## Phase 8: CLI (TDD)

### Task 8.1: cli.main with all flags

**Files:**
- Create: `src/heated_topics_v3/openbiliclaw_integration/cli.py`
- Test: `tests/openbiliclaw_integration/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openbiliclaw_integration/test_cli.py`:

```python
"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from heated_topics_v3.openbiliclaw_integration import cli


def test_parse_args_required() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_parse_args_defaults() -> None:
    args = cli.parse_args(["--users", "u.json", "--output", "o.json"])
    assert args.users == "u.json"
    assert args.output == "o.json"
    assert args.limit == 10
    assert args.max_parallel == 5
    assert args.body_preview_chars == 800
    assert args.providers is None


def test_parse_args_providers_comma_split() -> None:
    args = cli.parse_args([
        "--users", "u.json", "--output", "o.json",
        "--providers", "juejin,zhihu,toutiao",
    ])
    assert args.providers == ["juejin", "zhihu", "toutiao"]


def test_parse_args_max_parallel() -> None:
    args = cli.parse_args([
        "--users", "u.json", "--output", "o.json", "--max-parallel", "3"
    ])
    assert args.max_parallel == 3


def test_main_writes_output_file(tmp_path: Path) -> None:
    users = {"users": [{"user_id": "u0", "display_name": "U", "interests": [{"name": "x", "category": "x", "weight": 0.5}]}]}
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    fake_user_result = {"user_id": "u0", "display_name": "U", "recommendations": []}
    with patch.object(cli, "run_all_users_sync", return_value=[fake_user_result]):
        code = cli.main([
            "--users", str(up), "--output", str(out),
            "--max-parallel", "1",
        ])
    assert code == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "users" in data
    assert len(data["users"]) == 1


def test_main_returns_2_on_missing_users_file(tmp_path: Path) -> None:
    out = tmp_path / "recs.json"
    code = cli.main([
        "--users", str(tmp_path / "nope.json"),
        "--output", str(out),
    ])
    assert code == 2


def test_main_returns_2_on_validation_error(tmp_path: Path) -> None:
    up = tmp_path / "bad.json"
    up.write_text(json.dumps({"users": [{"display_name": "x", "interests": []}]}), encoding="utf-8")
    out = tmp_path / "recs.json"
    code = cli.main(["--users", str(up), "--output", str(out)])
    assert code == 2


def test_main_returns_1_on_partial_user_failure(tmp_path: Path) -> None:
    users = {"users": [
        {"user_id": "u0", "interests": [{"name": "x", "category": "x", "weight": 0.5}]},
        {"user_id": "u1", "interests": [{"name": "y", "category": "y", "weight": 0.5}]},
    ]}
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    fake = [
        {"user_id": "u0", "recommendations": []},
        {"user_id": "u1", "error": "boom"},
    ]
    with patch.object(cli, "run_all_users_sync", return_value=fake):
        code = cli.main([
            "--users", str(up), "--output", str(out), "--max-parallel", "1"
        ])
    assert code == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_cli.py -v
```
Expected: All FAIL with `ImportError`.

- [ ] **Step 3: Implement `cli.py`**

Create `src/heated_topics_v3/openbiliclaw_integration/cli.py`:

```python
"""CLI entry point for the openbiliclaw_integration recommender."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

from heated_topics_v3.openbiliclaw_integration import output, recommender, runtime
from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError

logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI args. Raises SystemExit on parse errors."""
    p = argparse.ArgumentParser(
        prog="python -m heated_topics_v3.openbiliclaw_integration.cli",
        description="Multi-user hot-article recommender (V3 providers + OpenBiliClaw).",
    )
    p.add_argument("--users", required=True, help="Path to users.json")
    p.add_argument("--output", required=True, help="Path to write recommendations.json")
    p.add_argument("--limit", type=int, default=10, help="Top-N per user (default 10)")
    p.add_argument(
        "--max-parallel", type=int, default=5,
        help="Max concurrent users (default 5; 1 = serial)",
    )
    p.add_argument(
        "--providers", default=None,
        help="Comma-separated provider list (default: all)",
    )
    p.add_argument(
        "--body-preview-chars", type=int, default=800,
        help="body_text_preview truncation length (default 800)",
    )
    p.add_argument(
        "--config", default="config/openbiliclaw.toml",
        help="OpenBiliClaw config path (default config/openbiliclaw.toml)",
    )
    p.add_argument(
        "--data-dir", default="data",
        help="Per-user data root (default data/)",
    )
    p.add_argument(
        "--per-user-timeout", type=float, default=60.0,
        help="Per-user timeout in seconds (default 60)",
    )
    return p.parse_args(list(argv))


def _exit_code_for(results: list[dict[str, Any]]) -> int:
    if not results:
        return 0
    if any("error" in r for r in results):
        return 1
    return 0


def run_all_users_sync(**kwargs: Any) -> list[dict[str, Any]]:
    """Sync wrapper for tests. Real implementation calls asyncio.run."""
    return asyncio.run(recommender.run_all_users(**kwargs))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. Returns process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # Fail-fast checks
    runtime.verify_patch()
    missing = runtime.check_env()
    if missing:
        logger.error("Missing env vars: %s", ", ".join(missing))
        return 2

    users_path = Path(args.users)
    output_path = Path(args.output)
    try:
        specs = recommender.load_users(users_path)
    except (FileNotFoundError, json.JSONDecodeError, ProfileValidationError) as exc:
        logger.error("users.json invalid: %s", exc)
        return 2
    if not specs:
        logger.error("users.json has zero users")
        return 2

    providers = args.providers.split(",") if args.providers else None
    data_dir = Path(args.data_dir)

    try:
        results = run_all_users_sync(
            users_path=users_path,
            data_dir=data_dir,
            max_parallel=args.max_parallel,
            limit=args.limit,
            body_preview_chars=args.body_preview_chars,
            per_user_timeout=args.per_user_timeout,
            providers=providers,
        )
    except Exception:
        logger.exception("fatal error in run_all_users")
        return 4

    envelope = output.build_envelope(
        users=results,
        llm_model="MiniMax-M2.7",
        embedding_model="bge-m3",
        config_version="0.3.186+mur.1",
    )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(output_path)
    except OSError as exc:
        logger.error("failed to write %s: %s", output_path, exc)
        return 4

    return _exit_code_for(results)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_cli.py -v
```
Expected: All PASS.

- [ ] **Step 5: Smoke test the CLI help output**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run python -m heated_topics_v3.openbiliclaw_integration.cli --help
```
Expected: argparse help text describing all flags.

- [ ] **Step 6: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/cli.py tests/openbiliclaw_integration/test_cli.py
git commit -m "feat(openbiliclaw_integration): CLI with all flags + exit codes"
```

---

## Phase 9: Real OpenBiliClaw runtime construction (real LLM/embedding)

### Task 9.1: Implement real `build_recommender` and `fetch_candidates`

**Files:**
- Modify: `src/heated_topics_v3/openbiliclaw_integration/recommender.py`
- Modify: `src/heated_topics_v3/openbiliclaw_integration/runtime.py`

- [ ] **Step 1: Add real `fetch_candidates` to recommender.py**

Replace the stub `fetch_candidates` in `src/heated_topics_v3/openbiliclaw_integration/recommender.py` with:

```python
def fetch_candidates(
    spec: user_profile.UserSpec,
    *,
    providers: list[str] | None = None,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch hot articles for one user from V3 providers.

    Each provider returns a list of Article dicts. We normalize to a flat
    list with a 'platform' field set per article.
    """
    enabled = providers or ["juejin", "baidu_hot", "zhihu_hot", "zhihu_daily", "toutiao"]
    out: list[dict[str, Any]] = []
    for platform in enabled:
        try:
            mod_name = f"heated_topics_v3.providers.{platform}"
            mod = __import__(mod_name, fromlist=["fetch_top"])
            articles = mod.fetch_top(limit=50)
        except Exception as exc:
            logger.warning("provider %s failed: %s", platform, exc)
            continue
        for art in articles:
            if isinstance(art, dict):
                art = {**art, "platform": platform}
                out.append(art)
    return out
```

- [ ] **Step 2: Add real `build_recommender` to recommender.py**

Add the following to `src/heated_topics_v3/openbiliclaw_integration/recommender.py` (after the stubs, replacing the `build_recommender` stub):

```python
def build_recommender(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    shared_runtime: Any | None = None,
    persist: bool = False,
) -> Any:
    """Build a per-user RecommendationEngine pointing at data_dir.

    LLM service and embedding service are shared across users
    (shared_runtime). Database, MemoryManager, and RecommendationEngine
    are per-user.
    """
    from openbiliclaw.recommendation.engine import RecommendationEngine
    from openbiliclaw.storage.database import Database
    from openbiliclaw.memory.manager import MemoryManager

    if shared_runtime is None:
        shared_runtime = _build_shared_runtime()

    user_db_path = data_dir / "openbiliclaw.db"
    user_db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(user_db_path)

    memory_manager = MemoryManager(data_dir, database=database)

    engine = RecommendationEngine(
        llm=shared_runtime["llm"],
        database=database,
        embedding_service=shared_runtime["embedding"],
        persist=persist,
    )
    return engine


def _build_shared_runtime() -> dict[str, Any]:
    """Construct shared LLM + embedding services. Called once at process start."""
    from openbiliclaw.llm.registry import build_default_registry
    from openbiliclaw.llm.service import LLMService

    registry = build_default_registry()
    llm_service = LLMService(registry=registry)
    return {
        "llm": llm_service,
        "embedding": None,  # wired by config in production; tests inject
    }
```

- [ ] **Step 3: Run unit tests to make sure they still pass with real impls behind mocks**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/ -v -k "not acceptance"
```
Expected: All unit + mock integration tests PASS (they mock build_recommender / fetch_candidates).

- [ ] **Step 4: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add src/heated_topics_v3/openbiliclaw_integration/recommender.py
git commit -m "feat(openbiliclaw_integration): real build_recommender + fetch_candidates"
```

---

## Phase 10: Patch verification + end-to-end mock integration tests

### Task 10.1: Patch presence test

**Files:**
- Create: `tests/openbiliclaw_integration/test_serve_external_patch.py`

- [ ] **Step 1: Write the test**

Create `tests/openbiliclaw_integration/test_serve_external_patch.py`:

```python
"""Verify the OpenBiliClaw patch is present and callable."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest


def test_serve_external_candidates_method_present() -> None:
    from openbiliclaw.recommendation.engine import RecommendationEngine
    assert hasattr(RecommendationEngine, "serve_external_candidates")
    assert asyncio.iscoroutinefunction(RecommendationEngine.serve_external_candidates)


def test_runtime_verify_patch_does_not_raise() -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime
    runtime.verify_patch()  # should be a no-op if patch is present
```

- [ ] **Step 2: Run the test**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_serve_external_patch.py -v
```
Expected: All PASS (patch is already in openbiliclaw-sandbox from Task 0.1).

- [ ] **Step 3: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add tests/openbiliclaw_integration/test_serve_external_patch.py
git commit -m "test(openbiliclaw_integration): verify OpenBiliClaw patch presence"
```

### Task 10.2: end-to-end one-user test (mocked engine, mocked LLM)

**Files:**
- Create: `tests/openbiliclaw_integration/test_end_to_end_one_user.py`

- [ ] **Step 1: Write the test**

Create `tests/openbiliclaw_integration/test_end_to_end_one_user.py`:

```python
"""End-to-end one-user test with mocked engine (real RecommendationEngine not called)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def test_end_to_end_one_user_writes_correct_envelope(tmp_path: Path) -> None:
    users = {"users": [
        {
            "user_id": "u_security",
            "display_name": "Sec",
            "interests": [{"name": "零信任", "category": "网安", "weight": 0.9}],
        }
    ]}
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"

    article = {
        "article_id": "1", "title": "T", "url": "https://x.com/1",
        "body_text": "body", "author": "a",
        "heat": {"view": 100, "like": 10, "comment": 2, "rank": 1},
        "tags": [],
        "platform": "juejin",
    }

    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation
    item = DiscoveredContent(
        title="T", content_id="1", content_url="https://x.com/1",
        source_platform="juejin", body_text="body", content_type="note",
    )
    fake_rec = Recommendation(
        content=item, expression="matches your interest",
        topic_label="网安", confidence=0.85, presented=False,
    )

    with patch.object(recommender, "fetch_candidates", return_value=[article]), \
         patch.object(recommender, "build_recommender") as mock_factory:
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng

        code = cli.main(["--users", str(up), "--output", str(out), "--max-parallel", "1"])

    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["users"][0]["user_id"] == "u_security"
    assert len(data["users"][0]["recommendations"]) == 1
    rec = data["users"][0]["recommendations"][0]
    assert rec["title"] == "T"
    assert rec["heat"]["view"] == 100
    assert rec["reason"] == "matches your interest"
    assert rec["topic_label"] == "网安"
    assert rec["body_text_preview"] == "body"
    assert rec["body_text_length"] == 4
    assert data["llm_model"] == "MiniMax-M2.7"
```

- [ ] **Step 2: Run the test**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_end_to_end_one_user.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add tests/openbiliclaw_integration/test_end_to_end_one_user.py
git commit -m "test(openbiliclaw_integration): end-to-end one-user mock test"
```

### Task 10.3: end-to-end multi-user test

**Files:**
- Create: `tests/openbiliclaw_integration/test_end_to_end_multi_user.py`

- [ ] **Step 1: Write the test**

Create `tests/openbiliclaw_integration/test_end_to_end_multi_user.py`:

```python
"""End-to-end multi-user test verifying per-user isolation in output JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def _fake_rec(user_id: str) -> Recommendation:
    item = DiscoveredContent(
        title=f"T-{user_id}", content_id=user_id,
        content_url=f"https://x.com/{user_id}",
        source_platform="juejin", body_text=f"body-{user_id}", content_type="note",
    )
    return Recommendation(
        content=item, expression=f"reason-{user_id}",
        topic_label=f"tp-{user_id}", confidence=0.7, presented=False,
    )


def test_end_to_end_three_users_independent_outputs(tmp_path: Path) -> None:
    users = {"users": [
        {"user_id": "u_a", "interests": [{"name": "x", "category": "x", "weight": 0.5}]},
        {"user_id": "u_b", "interests": [{"name": "y", "category": "y", "weight": 0.5}]},
        {"user_id": "u_c", "interests": [{"name": "z", "category": "z", "weight": 0.5}]},
    ]}
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    article = {
        "article_id": "1", "title": "T", "url": "https://x.com/1",
        "body_text": "body", "author": "a",
        "heat": {"view": 1, "like": 1, "comment": 1, "rank": 1},
        "tags": [],
        "platform": "juejin",
    }

    engines: dict[str, MagicMock] = {}
    def factory(spec, **kwargs):
        eng = MagicMock()
        engines[spec.user_id] = eng
        eng.serve_external_candidates = AsyncMock(
            return_value=[_fake_rec(spec.user_id)]
        )
        return eng

    with patch.object(recommender, "fetch_candidates", return_value=[article]), \
         patch.object(recommender, "build_recommender", side_effect=factory):
        code = cli.main([
            "--users", str(up), "--output", str(out), "--max-parallel", "3",
        ])

    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    by_user = {u["user_id"]: u for u in data["users"]}
    assert set(by_user) == {"u_a", "u_b", "u_c"}
    for uid, user in by_user.items():
        assert user["recommendations"][0]["title"] == f"T-{uid}"
        assert user["recommendations"][0]["topic_label"] == f"tp-{uid}"
    # Each user got its own engine instance
    assert len(engines) == 3
```

- [ ] **Step 2: Run the test**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_end_to_end_multi_user.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add tests/openbiliclaw_integration/test_end_to_end_multi_user.py
git commit -m "test(openbiliclaw_integration): end-to-end multi-user mock test"
```

---

## Phase 11: Config + Docs

### Task 11.1: openbiliclaw.toml.example

**Files:**
- Create: `config/openbiliclaw.toml.example`

- [ ] **Step 1: Create the example config**

Create `config/openbiliclaw.toml.example`:

```toml
# OpenBiliClaw config for the heatedTopics integration layer.
# Copy to config/openbiliclaw.toml and adjust paths / endpoints.
# API keys MUST come from env vars (OPENBILICLAW_LLM_API_KEY); never put
# them in this file.

[llm]
provider_type = "openai_compatible"
base_url = "https://api.minimaxi.com/v1"
model = "MiniMax-M2.7"
api_key_env = "OPENBILICLAW_LLM_API_KEY"

[embedding]
provider = "ollama"
model = "bge-m3"
base_url = "http://127.0.0.1:11434"

[recommendation]
mmr_alpha = 0.5
mmr_beta = 0.5
limit = 10

[paths]
data_dir = "data"
# Pool-source shares across providers (must sum <= 1.0)
pool_source_shares = { juejin = 0.30, zhihu_hot = 0.25, baidu_hot = 0.20, zhihu_daily = 0.15, toutiao = 0.10 }
```

- [ ] **Step 2: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add config/openbiliclaw.toml.example
git commit -m "docs(openbiliclaw_integration): example OpenBiliClaw config"
```

### Task 11.2: README

**Files:**
- Create: `docs/README-openbiliclaw-integration.md`

- [ ] **Step 1: Create the README**

Create `docs/README-openbiliclaw-integration.md`:

````markdown
# HeatedTopics × OpenBiliClaw 多用户推荐

CLI 接受多用户 JSON 画像，输出每个用户的 top-N 热点文章推荐（带热度、正文、理由、置信度）。

## 快速开始

```bash
# 1. 启动 Ollama + bge-m3
ollama serve &
ollama pull bge-m3

# 2. 配 LLM Key
export OPENBILICLAW_LLM_API_KEY=...

# 3. 准备配置
cp config/openbiliclaw.toml.example config/openbiliclaw.toml

# 4. 准备 users.json (见 tests/openbiliclaw_integration/fixtures/users_valid_3users.json)

# 5. 跑
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users users.json --output recs.json
```

## users.json 格式

必填：`user_id` + `interests`（≥1 个）。其余字段可选，详见 spec §数据流。

完整示例：`tests/openbiliclaw_integration/fixtures/users_valid_3users.json`。

## 输出 recs.json 格式

```json
{
  "generated_at": "2026-07-28T12:34:56Z",
  "config_version": "0.3.186+mur.1",
  "llm_model": "MiniMax-M2.7",
  "embedding_model": "bge-m3",
  "users": [
    {
      "user_id": "u1",
      "display_name": "...",
      "input_profile_summary": {...},
      "pipeline": {...},
      "recommendations": [
        {
          "rank": 1,
          "title": "...",
          "url": "...",
          "source_platform": "juejin",
          "heat": {"view": ..., "like": ..., "comment": ..., "rank": ...},
          "body_text_preview": "前 800 字…",
          "body_text_length": 2340,
          "topic_label": "...",
          "reason": "...",
          "confidence": 0.78,
          "published_at": "..."
        }
      ]
    }
  ]
}
```

## 故障排查

| 错误 | 原因 | 修复 |
|---|---|---|
| `OpenBiliClaw patch missing` | `openbiliclaw-sandbox` 未打 patch | 在 `E:\code\My\openbiliclaw-sandbox` 重打 `serve_external_candidates` |
| `Missing env vars: OPENBILICLAW_LLM_API_KEY` | 没设 key | `export OPENBILICLAW_LLM_API_KEY=...` |
| `Ollama at ... unreachable` | Ollama 没启动 | `ollama serve` |
| `Ollama has no 'bge-m3' model` | 模型未拉 | `ollama pull bge-m3` |
| 退出码 1 | 部分用户失败 | 看 recs.json `users[].error` 字段 |
| 退出码 4 | 写文件失败 | 检查 `--output` 路径权限 |

## CLI 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 所有用户成功 |
| 1 | 部分用户失败 |
| 2 | 启动期配置错误 |
| 3 | OpenBiliClaw 环境错误 |
| 4 | 写文件失败 |
| 130 | 用户中断 |
````

- [ ] **Step 2: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add docs/README-openbiliclaw-integration.md
git commit -m "docs(openbiliclaw_integration): README with quick start + troubleshooting"
```

---

## Phase 12: Acceptance tests (real MiniMax + Ollama, marked, CI skip)

### Task 12.1: acceptance test scaffolding

**Files:**
- Create: `tests/openbiliclaw_integration/test_acceptance_juejin.py`
- Create: `tests/openbiliclaw_integration/test_acceptance_multi_user.py`
- Create: `tests/openbiliclaw_integration/test_acceptance_degraded.py`

- [ ] **Step 1: Create `test_acceptance_juejin.py`**

Create `tests/openbiliclaw_integration/test_acceptance_juejin.py`:

```python
"""Real acceptance test: 1 user, real juejin, real MiniMax, real Ollama.

Skipped unless both OPENBILICLAW_LLM_API_KEY is set and Ollama is reachable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from heated_topics_v3.openbiliclaw_integration import cli, runtime


pytestmark = pytest.mark.requires_llm


def _ollama_reachable() -> bool:
    if shutil.which("ollama") is None:
        return False
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        return "bge-m3" in out.stdout
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_ollama() -> None:
    if not _ollama_reachable():
        pytest.skip("Ollama + bge-m3 not available")
    if not os.environ.get("OPENBILICLAW_LLM_API_KEY"):
        pytest.skip("OPENBILICLAW_LLM_API_KEY not set")


def test_acceptance_one_user_juejin(tmp_path: Path) -> None:
    users = {"users": [
        {"user_id": "u_acc", "display_name": "Acceptance",
         "interests": [{"name": "Rust", "category": "Rust", "weight": 0.9}],
         "disliked_topics": ["财经"]}
    ]}
    up = tmp_path / "users.json"
    up.write_text(__import__("json").dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    code = cli.main([
        "--users", str(up), "--output", str(out),
        "--max-parallel", "1", "--limit", "5",
        "--providers", "juejin",
    ])
    assert code == 0
    data = __import__("json").loads(out.read_text(encoding="utf-8"))
    user = data["users"][0]
    assert "error" not in user
    assert len(user["recommendations"]) <= 5
    for rec in user["recommendations"]:
        assert rec["heat"]["view"] >= 0
        assert rec["body_text_length"] >= 0
        assert rec["topic_label"] != "" or rec["reason"] != ""
```

- [ ] **Step 2: Create `test_acceptance_multi_user.py`**

Create `tests/openbiliclaw_integration/test_acceptance_multi_user.py`:

```python
"""Real acceptance test: 3 users with disjoint interests, real providers + LLM."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from heated_topics_v3.openbiliclaw_integration import cli


pytestmark = pytest.mark.requires_llm


def _ollama_reachable() -> bool:
    if shutil.which("ollama") is None:
        return False
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        return "bge-m3" in out.stdout
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_ollama() -> None:
    if not _ollama_reachable():
        pytest.skip("Ollama + bge-m3 not available")
    if not os.environ.get("OPENBILICLAW_LLM_API_KEY"):
        pytest.skip("OPENBILICLAW_LLM_API_KEY not set")


def test_acceptance_three_users(tmp_path: Path) -> None:
    users = {"users": [
        {"user_id": "u_rust", "interests": [{"name": "Rust", "category": "Rust", "weight": 0.95}]},
        {"user_id": "u_sec", "interests": [{"name": "零信任", "category": "网安", "weight": 0.95}]},
        {"user_id": "u_design", "interests": [{"name": "UI 排版", "category": "设计", "weight": 0.95}]},
    ]}
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    code = cli.main([
        "--users", str(up), "--output", str(out),
        "--max-parallel", "3", "--limit", "5",
    ])
    # Some users may fail if their interests don't match fetched articles; that's OK
    assert code in (0, 1)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["users"]) == 3
```

- [ ] **Step 3: Create `test_acceptance_degraded.py`**

Create `tests/openbiliclaw_integration/test_acceptance_degraded.py`:

```python
"""Real acceptance test: degraded path with Ollama stopped before the run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from heated_topics_v3.openbiliclaw_integration import cli


pytestmark = pytest.mark.requires_llm


def _stop_ollama() -> None:
    if shutil.which("ollama") is None:
        return
    try:
        subprocess.run(["ollama", "stop", "bge-m3"], capture_output=True, timeout=5)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def require_llm() -> None:
    if not os.environ.get("OPENBILICLAW_LLM_API_KEY"):
        pytest.skip("OPENBILICLAW_LLM_API_KEY not set")


def test_acceptance_embedding_degraded(tmp_path: Path) -> None:
    users = {"users": [
        {"user_id": "u_deg", "interests": [{"name": "Rust", "category": "Rust", "weight": 0.9}]}
    ]}
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    _stop_ollama()
    try:
        code = cli.main([
            "--users", str(up), "--output", str(out),
            "--max-parallel", "1", "--limit", "3",
            "--providers", "juejin",
        ])
    finally:
        # Best-effort restart
        try:
            subprocess.Popen(["ollama", "serve"])
        except Exception:
            pass
    # Should still produce results in degraded mode
    assert code in (0, 1)
    data = json.loads(out.read_text(encoding="utf-8"))
    user = data["users"][0]
    # Either succeeded with degraded flag or hit a non-Ollama issue
    if "pipeline" in user:
        # If pipeline ran, embedding_degraded should be true (Ollama was down)
        assert user["pipeline"].get("embedding_degraded") is True
```

- [ ] **Step 4: Add pytest markers in pyproject.toml**

Open `pyproject.toml`. Under `[tool.pytest.ini_options]` (or create if absent):

```toml
[tool.pytest.ini_options]
markers = [
    "requires_llm: requires real MiniMax API + Ollama",
    "requires_ollama: requires Ollama with bge-m3",
]
asyncio_mode = "auto"
```

- [ ] **Step 5: Verify acceptance tests are skipped (not run) in default pytest**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/test_acceptance_*.py -v
```
Expected: All acceptance tests collected but skipped (no API key, no Ollama).

- [ ] **Step 6: Commit**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add tests/openbiliclaw_integration/test_acceptance_*.py pyproject.toml
git commit -m "test(openbiliclaw_integration): real-acceptance tests (CI skip by default)"
```

---

## Phase 13: Final verification

### Task 13.1: ruff + format check

- [ ] **Step 1: Run ruff check**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run ruff check src/heated_topics_v3/openbiliclaw_integration/ tests/openbiliclaw_integration/
```
Expected: no errors (or only fixable style issues).

- [ ] **Step 2: Run ruff format**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run ruff format src/heated_topics_v3/openbiliclaw_integration/ tests/openbiliclaw_integration/
```
Expected: no changes (already formatted), or auto-formatted.

- [ ] **Step 3: Commit any formatting changes**

If `git status` shows changes:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add -u src/heated_topics_v3/openbiliclaw_integration/ tests/openbiliclaw_integration/
git commit -m "style: ruff format"
```

### Task 13.2: Full test suite + coverage

- [ ] **Step 1: Run all unit + mock integration tests**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/ -v -k "not acceptance"
```
Expected: All PASS.

- [ ] **Step 2: Run with coverage**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run pytest tests/openbiliclaw_integration/ -k "not acceptance" \
  --cov=heated_topics_v3.openbiliclaw_integration \
  --cov-report=term-missing
```
Expected: Coverage ≥ 80% on the integration layer.

- [ ] **Step 3: Commit coverage config (if added)**

If you added `[tool.coverage]` to pyproject.toml, commit it:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git add pyproject.toml
git commit -m "build: pytest coverage config"
```

### Task 13.3: Final end-to-end smoke test (no real LLM needed)

- [ ] **Step 1: Inject a mocked users.json + run CLI**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run python -m heated_topics_v3.openbiliclaw_integration.cli --users tests/openbiliclaw_integration/fixtures/users_valid_3users.json --output /tmp/recs.json --max-parallel 1
```
Expected: Either exit 0 (real run succeeds if MiniMax+Ollama are up) or exit 2 (env var missing). Verify CLI parses args, validates users.json (no schema error), and produces a sensible error message.

- [ ] **Step 2: Verify CLI help**

Run:
```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
uv run python -m heated_topics_v3.openbiliclaw_integration.cli --help
```
Expected: argparse help text for all 9 flags.

- [ ] **Step 3: Final commit (if any loose ends)**

```bash
cd "E:/.code/My/heatedTopics/heatedTopics/.worktrees/openbiliclaw-multi-user-recommender"
git status
# If anything uncommitted:
git add -A
git commit -m "chore: final cleanup"
```

---

## Completion Checklist

- [ ] All 13 phases complete
- [ ] `uv run pytest tests/openbiliclaw_integration/ -k "not acceptance"` passes
- [ ] `uv run ruff check` passes
- [ ] `uv run ruff format` applied
- [ ] Coverage ≥ 80% on `heated_topics_v3.openbiliclaw_integration`
- [ ] OpenBiliClaw patch committed in `openbiliclaw-sandbox` (`feat(recommendation): add serve_external_candidates...`)
- [ ] README + example config committed
- [ ] `python -m heated_topics_v3.openbiliclaw_integration.cli --help` works
- [ ] (Optional) Acceptance tests pass locally with MiniMax + Ollama
