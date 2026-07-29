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
    return json.loads(
        (FIXTURES_DIR / "users_valid_3users.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tmp_users_path(tmp_path: Path, users_valid_3users: dict[str, Any]) -> Path:
    p = tmp_path / "users.json"
    p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return p
