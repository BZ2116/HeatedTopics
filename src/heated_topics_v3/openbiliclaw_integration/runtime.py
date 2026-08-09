"""OpenBiliClaw runtime construction (LLM, embedding, per-user engine)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def configure_model_env(config: Any) -> Any:
    """Apply provider-neutral model environment variables to an OpenBiliClaw config.

    ``HT_*`` names are preferred; common ``LLM_*`` / ``EMBEDDING_*`` aliases
    are accepted for easy integration with existing deployments. Explicit
    TOML values remain valid and are only replaced when an environment value
    is present.
    """
    llm_provider = os.getenv("HT_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "")).strip().lower()
    llm_key = os.getenv("HT_LLM_API_KEY", os.getenv("LLM_API_KEY", os.getenv("OPENBILICLAW_LLM_API_KEY", ""))).strip()
    llm_model = os.getenv("HT_LLM_MODEL", os.getenv("LLM_MODEL", "")).strip()
    llm_base = os.getenv("HT_LLM_BASE_URL", os.getenv("LLM_BASE_URL", "")).strip()
    if llm_provider or llm_key or llm_model or llm_base:
        provider = llm_provider or str(config.llm.default_provider or "openai_compatible").lower()
        if provider not in {"openai", "claude", "gemini", "deepseek", "ollama", "openrouter", "openai_compatible"}:
            provider = "openai_compatible"
        config.llm.default_provider = provider
        provider_cfg = getattr(config.llm, provider)
        if llm_key:
            provider_cfg.api_key = llm_key
        if llm_model:
            provider_cfg.model = llm_model
        if llm_base:
            provider_cfg.base_url = llm_base

    emb_provider = os.getenv("HT_EMBEDDING_PROVIDER", os.getenv("EMBEDDING_PROVIDER", "")).strip().lower()
    emb_key = os.getenv("HT_EMBEDDING_API_KEY", os.getenv("EMBEDDING_API_KEY", "")).strip()
    emb_model = os.getenv("HT_EMBEDDING_MODEL", os.getenv("EMBEDDING_MODEL", "")).strip()
    emb_base = os.getenv("HT_EMBEDDING_BASE_URL", os.getenv("EMBEDDING_BASE_URL", "")).strip()
    if emb_provider or emb_key or emb_model or emb_base:
        if emb_provider:
            config.llm.embedding.provider = emb_provider
        if emb_key:
            config.llm.embedding.api_key = emb_key
        if emb_model:
            config.llm.embedding.model = emb_model
        if emb_base:
            config.llm.embedding.base_url = emb_base
    return config


def load_openbiliclaw_config(path: str | Path) -> Any | None:
    """Load an OpenBiliClaw config.toml. Returns None on missing file.

    The loaded config is augmented with chat + embedding defaults before
    being returned: when ``[llm]`` doesn't already define
    ``[llm.instances.MiniMax]``, we add a v2 route pointing at the
    MiniMax ``openai_compatible`` endpoint so that
    ``build_llm_registry`` always has a chat provider.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        from openbiliclaw.config import LLMInstanceConfig, load_config  # type: ignore

        config = load_config(p)
    except Exception as exc:
        logger.warning("Failed to load OpenBiliClaw config from %s: %s", p, exc)
        return None

    api_key = os.environ.get("OPENBILICLAW_LLM_API_KEY", "").strip()
    if api_key and not config.llm.instances:
        config.llm.instances["minimax"] = LLMInstanceConfig(
            name="minimax",
            provider_type="openai_compatible",
            enabled=True,
            api_key=api_key,
            model="MiniMax-M2.7",
            base_url="https://api.minimaxi.com/v1",
        )
        config.llm.default_chain = ["minimax"]
        config.llm.default_provider = "openai_compatible"
        config.llm.instance_routing = True
    # TOML ``api_key_env`` is silently dropped by load_config — the loader
    # only understands ``api_key``. Fill any empty ``api_key`` from the
    # canonical env var so users can write ``api_key_env`` in TOML as
    # documentation without it being a footgun.
    for inst in config.llm.instances.values():
        if not inst.api_key.strip() and api_key:
            inst.api_key = api_key
    # Normalize instance keys + default_chain to lowercase. The registry
    # lowercases the chain and looks up instances case-sensitively, so a
    # mixed-case key like ``MiniMax`` is silently dropped.
    config.llm.instances = {
        k.lower(): v for k, v in config.llm.instances.items()
    }
    config.llm.default_chain = [str(x).strip().lower() for x in config.llm.default_chain]
    if not config.llm.embedding.provider.strip():
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"
    return configure_model_env(config)


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
