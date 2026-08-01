"""Tests for simplified v2 UserSpec."""

from __future__ import annotations

import pytest

from heated_topics_v3.openbiliclaw_integration.user_profile import (
    ProfileValidationError,
    UserSpec,
    load_users,
)


def test_userspec_has_minimal_fields() -> None:
    spec = UserSpec(user_id="u1", track_1="AI", track_2="副业", persona="博主")
    assert spec.user_id == "u1"
    assert spec.track_1 == "AI"
    assert spec.track_2 == "副业"
    assert spec.persona == "博主"


def test_userspec_display_name_defaults_to_user_id() -> None:
    spec = UserSpec(user_id="u1", track_1="AI", track_2="x", persona="p")
    assert spec.display_name == "u1"


def test_userspec_rejects_empty_track_1() -> None:
    with pytest.raises(ProfileValidationError):
        UserSpec(user_id="u1", track_1="", track_2="x", persona="p")


def test_userspec_rejects_empty_user_id() -> None:
    with pytest.raises(ProfileValidationError):
        UserSpec(user_id="", track_1="AI", track_2="x", persona="p")


def test_load_users_accepts_dicts() -> None:
    specs = load_users(
        [{"user_id": "u1", "track_1": "AI", "track_2": "x", "persona": "p"}]
    )
    assert len(specs) == 1 and specs[0].user_id == "u1"


def test_load_users_rejects_non_dict() -> None:
    with pytest.raises(ProfileValidationError):
        load_users(["not a dict"])