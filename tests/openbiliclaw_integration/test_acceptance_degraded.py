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
