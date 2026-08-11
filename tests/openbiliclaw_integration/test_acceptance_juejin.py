"""Real acceptance test: 1 user, real juejin, real MiniMax, real Ollama.

Skipped unless both OPENBILICLAW_LLM_API_KEY is set and Ollama is reachable.
"""

from __future__ import annotations

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
    users = {
        "users": [
            {
                "user_id": "u_acc",
                "display_name": "Acceptance",
                "interests": [{"name": "Rust", "category": "Rust", "weight": 0.9}],
                "disliked_topics": ["财经"],
            }
        ]
    }
    up = tmp_path / "users.json"
    up.write_text(__import__("json").dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    code = cli.main(
        [
            "--users",
            str(up),
            "--output",
            str(out),
            "--max-parallel",
            "1",
            "--limit",
            "5",
            "--providers",
            "juejin",
        ]
    )
    assert code == 0
    data = __import__("json").loads(out.read_text(encoding="utf-8"))
    user = data["users"][0]
    assert "error" not in user
    assert len(user["recommendations"]) <= 5
    for rec in user["recommendations"]:
        assert rec["heat"]["view"] >= 0
        assert rec["body_text_length"] >= 0
        assert rec["topic_label"] != "" or rec["reason"] != ""
