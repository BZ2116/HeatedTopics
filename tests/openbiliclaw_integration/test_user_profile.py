"""Tests for user_profile module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heated_topics_v3.openbiliclaw_integration import user_profile
from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError


def test_load_users_returns_list_of_user_specs(tmp_path: Path, users_valid_3users: dict) -> None:
    p = tmp_path / "users.json"
    p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    specs = user_profile.load_users(p)
    assert len(specs) == 3
    assert specs[0].user_id == "u_security"
    assert specs[1].interests[0].name == "Tokio 异步运行时"


def test_load_users_raises_on_missing_user_id(fixtures_dir: Path) -> None:
    p = fixtures_dir / "users_invalid_missing_user_id.json"
    with pytest.raises(ProfileValidationError) as exc:
        user_profile.load_users(p)
    assert "user_id" in str(exc.value).lower() or "u_" in str(exc.value)


def test_load_users_raises_on_empty_interests(fixtures_dir: Path) -> None:
    p = fixtures_dir / "users_invalid_empty_interests.json"
    with pytest.raises(ProfileValidationError) as exc:
        user_profile.load_users(p)
    assert "interests" in str(exc.value).lower()


def test_load_users_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        user_profile.load_users(tmp_path / "nope.json")


def test_load_users_raises_on_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json {{{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        user_profile.load_users(p)


def test_load_users_raises_on_missing_top_level_users_key(tmp_path: Path) -> None:
    p = tmp_path / "no_users.json"
    p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    with pytest.raises(ProfileValidationError) as exc:
        user_profile.load_users(p)
    assert "users" in str(exc.value).lower()


def test_user_spec_interest_weight_out_of_range_raises(tmp_path: Path) -> None:
    bad = {"users": [{"user_id": "x", "interests": [{"name": "a", "category": "a", "weight": 1.5}]}]}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ProfileValidationError):
        user_profile.load_users(p)


def test_build_onion_profile_populates_layers(tmp_path: Path, users_valid_3users: dict) -> None:
    p = tmp_path / "users.json"
    p.write_text(json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8")
    specs = user_profile.load_users(p)
    profile = user_profile.build_onion_profile(specs[0])
    assert profile.life_stage == "本科大四"
    assert "好奇心强" in profile.core.core_traits
    assert len(profile.recent_awareness) == 1
    assert profile.recent_awareness[0].observation == "在看 RAG 注入攻防"
    assert profile.preferences.disliked_topics == ["娱乐八卦", "纯财经快讯"]
    assert profile.surface.exploration_openness == pytest.approx(0.6)


def test_user_data_dir_creates_directory(tmp_path: Path) -> None:
    d = user_profile.user_data_dir(tmp_path, "u_security/with/slash")
    assert d.is_dir()
    assert d.parent.name == "users"
    # Slashes converted to underscores
    assert "_" in d.name or d.name == "u_security_with_slash"


def test_user_data_dir_idempotent(tmp_path: Path) -> None:
    d1 = user_profile.user_data_dir(tmp_path, "u_a")
    d2 = user_profile.user_data_dir(tmp_path, "u_a")
    assert d1 == d2
