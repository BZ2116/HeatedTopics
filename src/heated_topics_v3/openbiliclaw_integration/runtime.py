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
            return (
                False,
                f"Ollama at {base_url} has no 'bge-m3' model; run `ollama pull bge-m3`",
            )
        return True, "ok"
    except Exception as exc:
        return False, f"Ollama at {base_url} unreachable: {exc}"
