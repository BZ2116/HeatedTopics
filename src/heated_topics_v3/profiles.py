"""Persistence helpers for user profiles."""

import json
from dataclasses import asdict
from pathlib import Path

from heated_topics_v3.contracts import UserProfile


def _validate(profile: UserProfile) -> UserProfile:
    if not profile.primary_keyword.strip():
        raise ValueError("primary_keyword must not be empty")
    return profile


def load_profile(path: Path) -> UserProfile:
    """Load and validate a UTF-8 JSON user profile."""
    profile = UserProfile(**json.loads(path.read_text(encoding="utf-8")))
    return _validate(profile)


def save_profile(profile: UserProfile, path: Path) -> None:
    """Validate and save a user profile as readable UTF-8 JSON."""
    _validate(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
