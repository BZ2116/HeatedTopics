"""Tests for LLM-driven keyword extraction + per-user cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from heated_topics_v3.openbiliclaw_integration import keyword_extractor
from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec


def _spec(
    user_id: str = "u1",
    track_1: str = "非遗",
    track_2: str = "民俗",
    persona: str = "研究地方习俗",
) -> UserSpec:
    return UserSpec(
        user_id=user_id, track_1=track_1, track_2=track_2, persona=persona,
    )


def test_spec_hash_stable_for_same_input() -> None:
    h1 = keyword_extractor._spec_hash(_spec())
    h2 = keyword_extractor._spec_hash(_spec())
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_spec_hash_changes_when_track_1_changes() -> None:
    h1 = keyword_extractor._spec_hash(_spec(track_1="非遗"))
    h2 = keyword_extractor._spec_hash(_spec(track_1="手工艺"))
    assert h1 != h2


def test_spec_hash_changes_when_persona_changes() -> None:
    h1 = keyword_extractor._spec_hash(_spec(persona="研究地方习俗"))
    h2 = keyword_extractor._spec_hash(_spec(persona="关注乡村振兴"))
    assert h1 != h2
