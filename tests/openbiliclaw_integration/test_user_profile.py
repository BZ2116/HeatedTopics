"""Tests for simplified v2 UserSpec."""

from __future__ import annotations

import pytest

from heated_topics_v3.openbiliclaw_integration.user_profile import (
    ProfileValidationError,
    UserSpec,
    load_users,
    user_id_for_spec,
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


def test_user_id_for_spec_is_stable_across_calls() -> None:
    """Same content → same u_xxx, regardless of how many times we ask."""
    a = UserSpec("u_X", track_1="AI", track_2="副业", persona="博主")
    b = UserSpec("u_Y", track_1="AI", track_2="副业", persona="博主")
    assert user_id_for_spec(a) == user_id_for_spec(b)
    assert user_id_for_spec(a) == user_id_for_spec(a)


def test_user_id_for_spec_changes_when_track_changes() -> None:
    base = UserSpec("u", track_1="美食", track_2="探店", persona="博主")
    flipped = UserSpec("u", track_1="探店", track_2="美食", persona="博主")
    assert user_id_for_spec(base) != user_id_for_spec(flipped)


def test_user_id_for_spec_separates_same_tracks_but_different_persona() -> None:
    """tracks-only collision risk: persona is part of the hash, so they differ."""
    p1 = UserSpec("u", track_1="美食", track_2="探店", persona="博主A")
    p2 = UserSpec("u", track_1="美食", track_2="探店", persona="博主B")
    assert user_id_for_spec(p1) != user_id_for_spec(p2)


def test_user_id_for_spec_format() -> None:
    """Eight-hex chars after 'u_'."""
    spec = UserSpec("u", track_1="AI", track_2="x", persona="p")
    uid = user_id_for_spec(spec)
    assert uid.startswith("u_")
    assert len(uid) == 2 + 8
    int(uid[2:], 16)
