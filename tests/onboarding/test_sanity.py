"""Environment self-check tests for a fresh agent.

Run first::

    pytest tests/onboarding/test_sanity.py -v
    # or just:
    pytest -m sanity -v

Each test fails with a message describing the exact fix. Fix and re-run
until all sanity tests pass; only then will the unit suite and end-to-end
smoke tests be reliable.

The tests are deliberately strict: if anything is missing they fail with
"here's what's wrong and how to fix it" rather than skipping silently.
"""

from __future__ import annotations

import os
import sys

import pytest


@pytest.mark.sanity
def test_python_version_is_at_least_3_11() -> None:
    """Project requires-python is '>=3.11' (openbiliclaw enforces this)."""
    v = sys.version_info
    assert (v.major, v.minor) >= (3, 11), (
        f"Python {v.major}.{v.minor} detected; need 3.11+.\n"
        f"Fix: install Python 3.11 or 3.12 and recreate the venv "
        f"(`uv python install 3.11`, then `uv sync`)."
    )


@pytest.mark.sanity
def test_core_dependencies_are_importable() -> None:
    """Verify all runtime deps import without error.

    If any import fails, the missing package name is reported so the agent
    can `uv add <package>` (or `uv sync`) directly.
    """
    missing: list[str] = []
    for name in ("openpyxl", "httpx", "openbiliclaw"):
        try:
            __import__(name)
        except ImportError as exc:
            missing.append(f"{name}: {exc}")
    try:
        from dotenv import load_dotenv  # noqa: F401
    except ImportError as exc:
        missing.append(f"python-dotenv: {exc}")
    assert not missing, (
        "Missing runtime dependencies:\n  - "
        + "\n  - ".join(missing)
        + "\nFix: `uv sync` (or `uv add <pkg>` for the named packages)."
    )


@pytest.mark.sanity
def test_openbiliclaw_patch_is_present() -> None:
    """serve_external_candidates must exist on RecommendationEngine.

    The package is wired against openbiliclaw-sandbox, which carries a
    patch adding this method. Without it, the CLI aborts at startup.
    """
    from openbiliclaw.recommendation.engine import RecommendationEngine

    has = hasattr(RecommendationEngine, "serve_external_candidates")
    assert has, (
        "OpenBiliClaw patch missing: RecommendationEngine has no "
        "'serve_external_candidates' method.\n"
        "Fix: clone openbiliclaw-sandbox and apply the patch listed in "
        "the README §One-time setup (commit 'feat(recommendation): add "
        "serve_external_candidates'), then `pip install -e openbiliclaw-sandbox`."
    )


@pytest.mark.sanity
def test_llm_api_key_env_var_is_set() -> None:
    """OPENBILICLAW_LLM_API_KEY must be set before the pipeline runs."""
    key = os.environ.get("OPENBILICLAW_LLM_API_KEY", "").strip()
    assert key, (
        "OPENBILICLAW_LLM_API_KEY is not set.\n"
        "Fix: `export OPENBILICLAW_LLM_API_KEY=sk-...` (or set it in "
        ".env at the repo root). The CLI exits with code 2 without it."
    )


@pytest.mark.sanity
def test_ollama_is_reachable_with_bge_m3_model() -> None:
    """Embedding service must be live on 127.0.0.1:11434 with bge-m3."""
    from heated_topics_v3.openbiliclaw_integration.runtime import check_ollama

    ok, msg = check_ollama()
    assert ok, (
        f"{msg}\n"
        f"Fix: `ollama serve` (in another shell) and `ollama pull bge-m3`."
    )


@pytest.mark.sanity
def test_runtime_helpers_are_wired() -> None:
    """The runtime helpers used by CLI entry / CLI internals exist and work.

    This is a smoke test for the integration layer itself: ``verify_patch``
    raises if the patch is missing (already covered above), but checking
    that the helpers compose cleanly catches import regressions early.
    """
    from heated_topics_v3.openbiliclaw_integration import runtime

    runtime.verify_patch()  # raises RuntimeError if patch missing
    assert isinstance(runtime.check_env(), list)
    ok, message = runtime.check_ollama()
    assert ok, (
        f"Ollama self-check failed: {message}\n"
        f"Fix: see test_ollama_is_reachable_with_bge_m3_model."
    )


@pytest.mark.sanity
def test_recommender_modules_import() -> None:
    """All top-level integration modules must be importable."""
    expected = (
        "candidate_adapter",
        "cli",
        "exceptions",
        "excel_loader",
        "keyword_extractor",
        "last30days_adapter",
        "last30days_source",
        "llm_refilter",
        "per_query_summary",
        "recommender",
        "relevance",
        "report_writer",
        "runtime",
        "user_profile",
    )
    import importlib

    package = "heated_topics_v3.openbiliclaw_integration"
    missing: list[str] = []
    for name in expected:
        try:
            importlib.import_module(f"{package}.{name}")
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{name}: {exc}")
    assert not missing, (
        "These integration modules failed to import:\n  - "
        + "\n  - ".join(missing)
        + "\nFix: re-run `uv sync` and check for syntax/import errors."
    )