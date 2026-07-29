"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from heated_topics_v3.openbiliclaw_integration import cli


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() requires the LLM API key env var; set a dummy value for tests."""
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")


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
