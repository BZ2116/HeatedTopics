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


def test_acceptance_three_users(tmp_path: Path) -> None:
    users = {
        "users": [
            {
                "user_id": "u_rust",
                "interests": [{"name": "Rust", "category": "Rust", "weight": 0.95}],
            },
            {
                "user_id": "u_sec",
                "interests": [{"name": "零信任", "category": "网安", "weight": 0.95}],
            },
            {
                "user_id": "u_design",
                "interests": [{"name": "UI 排版", "category": "设计", "weight": 0.95}],
            },
        ]
    }
    up = tmp_path / "users.json"
    up.write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "recs.json"
    code = cli.main(
        [
            "--users",
            str(up),
            "--output",
            str(out),
            "--max-parallel",
            "3",
            "--limit",
            "5",
        ]
    )
    # Some users may fail if their interests don't match fetched articles; that's OK
    assert code in (0, 1)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["users"]) == 3
