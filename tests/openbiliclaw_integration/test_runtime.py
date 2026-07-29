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


def test_verify_patch_present() -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime

    runtime.verify_patch()  # should not raise
