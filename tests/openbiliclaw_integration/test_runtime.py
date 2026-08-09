"""Tests for runtime module (OpenBiliClaw service construction)."""

from __future__ import annotations

from pathlib import Path


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


def test_configure_model_env_supports_generic_llm_and_embedding(monkeypatch) -> None:
    from openbiliclaw.config import Config
    from heated_topics_v3.openbiliclaw_integration import runtime

    monkeypatch.setenv("HT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("HT_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("HT_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("HT_LLM_MODEL", "chat-model")
    monkeypatch.setenv("HT_EMBEDDING_PROVIDER", "openai_compatible")
    monkeypatch.setenv("HT_EMBEDDING_API_KEY", "emb-key")
    monkeypatch.setenv("HT_EMBEDDING_BASE_URL", "https://emb.example/v1")
    monkeypatch.setenv("HT_EMBEDDING_MODEL", "embed-model")

    cfg = runtime.configure_model_env(Config())
    assert cfg.llm.default_provider == "openai_compatible"
    assert cfg.llm.openai_compatible.api_key == "llm-key"
    assert cfg.llm.openai_compatible.base_url == "https://llm.example/v1"
    assert cfg.llm.openai_compatible.model == "chat-model"
    assert cfg.llm.embedding.provider == "openai_compatible"
    assert cfg.llm.embedding.api_key == "emb-key"
    assert cfg.llm.embedding.base_url == "https://emb.example/v1"
    assert cfg.llm.embedding.model == "embed-model"


def test_configure_model_env_does_not_let_blank_ht_values_hide_legacy(monkeypatch) -> None:
    from openbiliclaw.config import Config
    from heated_topics_v3.openbiliclaw_integration import runtime

    monkeypatch.setenv("HT_LLM_API_KEY", "")
    monkeypatch.setenv("HT_LLM_BASE_URL", "")
    monkeypatch.setenv("HT_LLM_MODEL", "")
    monkeypatch.setenv("MINIMAX_API_KEY", "legacy-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("MINIMAX_MODEL", "legacy-model")

    cfg = runtime.configure_model_env(Config())
    assert cfg.llm.openai_compatible.api_key == "legacy-key"
    assert cfg.llm.openai_compatible.base_url == "https://legacy.example/v1"
    assert cfg.llm.openai_compatible.model == "legacy-model"


def test_load_openbiliclaw_config_normalizes_instance_keys_to_lowercase(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: build_llm_registry lowercases default_chain but looks up
    instance keys case-sensitively. Mixed-case keys silently drop the
    provider. ``load_openbiliclaw_config`` must normalize to lowercase so
    the registry actually finds the instance.
    """
    from heated_topics_v3.openbiliclaw_integration import runtime

    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key-abc")
    cfg_path = tmp_path / "obc.toml"
    cfg_path.write_text(
        "[llm]\n"
        "routing_version = 2\n"
        "default_chain = ['MiniMax']\n\n"
        "[llm.instances.MiniMax]\n"
        "provider_type = 'openai_compatible'\n"
        "model = 'm'\n"
        "base_url = 'https://x'\n",
        encoding="utf-8",
    )
    cfg = runtime.load_openbiliclaw_config(cfg_path)
    assert cfg is not None
    assert all(k == k.lower() for k in cfg.llm.instances)
    assert cfg.llm.instances["minimax"].api_key == "test-key-abc"
    assert cfg.llm.default_chain == ["minimax"]


def test_load_openbiliclaw_config_fills_empty_api_key_from_env(
    tmp_path: Path, monkeypatch
) -> None:
    """TOML ``api_key_env`` is silently dropped by load_config; runtime must
    fall back to the canonical env var so the provider is actually usable.
    """
    from heated_topics_v3.openbiliclaw_integration import runtime

    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "env-key-xyz")
    cfg_path = tmp_path / "obc.toml"
    cfg_path.write_text(
        "[llm]\n"
        "default_chain = ['minimax']\n\n"
        "[llm.instances.minimax]\n"
        "provider_type = 'openai_compatible'\n"
        "model = 'm'\n"
        "base_url = 'https://x'\n",
        encoding="utf-8",
    )
    cfg = runtime.load_openbiliclaw_config(cfg_path)
    assert cfg is not None
    assert cfg.llm.instances["minimax"].api_key == "env-key-xyz"


def test_verify_patch_present() -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime

    runtime.verify_patch()  # should not raise
