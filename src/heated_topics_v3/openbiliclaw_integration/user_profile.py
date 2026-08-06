"""Minimal v2 user profile + OpenBiliClaw adapter.

Pipeline:
  load_users()           ->  list[UserSpec]       (from list[dict] — xlsx rows)
  UserSpec               ->  OnionProfile          (via build_onion_profile())

The v2 schema intentionally drops the rich fields (interests/disliked_topics/
core_traits/deep_needs/values/cognitive_style/recent_awareness/active_insights/
life_stage/current_phase/exploration_openness/source_platform_mix/favorite_up_users/style/context)
that v1 carried. Track_1 + track_2 are the only ranking signals; persona is
metadata for downstream consumers (engine currently ignores it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbiliclaw.soul.profile import OnionProfile

from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError


@dataclass(frozen=True)
class UserSpec:
    """Minimal v2 user profile: identity + 2 tracks + persona."""

    user_id: str
    display_name: str = ""
    track_1: str = ""
    track_2: str = ""
    persona: str = ""

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ProfileValidationError("user_id is required")
        if not self.track_1.strip():
            raise ProfileValidationError("track_1 is required")
        if not self.display_name:
            object.__setattr__(self, "display_name", self.user_id)


def _spec_hash(spec: UserSpec) -> str:
    """Stable sha256 of the spec fields that influence ranking.

    Used as both the per-user cache key (keyword_extractor) and the basis
    for the cross-run stable ``user_id``. user_id is intentionally excluded:
    changing the ID means a new user, not an updated one.
    """
    blob = f"{spec.track_1}\x00{spec.track_2}\x00{spec.persona}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def user_id_for_spec(spec: UserSpec) -> str:
    """Return a cross-run-stable ``user_id`` derived from spec content.

    Two specs with the same ``track_1`` / ``track_2`` / ``persona`` map to
    the same id regardless of the caller's preferred display name; this
    means re-running with the same Excel always groups under the same id
    while a content change shifts the id. 8-hex truncation gives ~4.29B
    space — collision-free at any realistic user scale.
    """
    return "u_" + _spec_hash(spec)[:8]


def load_users(specs: list[dict[str, Any]]) -> list[UserSpec]:
    """Build UserSpec list from raw dicts (typically from xlsx rows)."""
    out: list[UserSpec] = []
    for raw in specs:
        if not isinstance(raw, dict):
            raise ProfileValidationError(
                f"expected dict per user, got {type(raw).__name__}"
            )
        out.append(
            UserSpec(
                user_id=str(raw.get("user_id") or "").strip(),
                display_name=str(raw.get("display_name") or "").strip(),
                track_1=str(raw.get("track_1") or "").strip(),
                track_2=str(raw.get("track_2") or "").strip(),
                persona=str(raw.get("persona") or "").strip(),
            )
        )
    return out


def build_onion_profile(spec: UserSpec) -> OnionProfile:
    """Map v2 UserSpec → openbiliclaw OnionProfile.

    Only `interests` (driven by track_1/track_2) influences engine ranking.
    Other fields default to empty — engine treats them as no-op.
    `personality_portrait` carries the persona string (currently unused by
    `build_profile_summary` but preserved for forward compatibility).
    """
    interests: list[dict[str, Any]] = []
    for track in (spec.track_1, spec.track_2):
        t = track.strip()
        if t:
            interests.append({"name": t, "category": "", "weight": 0.8})
    profile_dict = {
        "core": {"interests": interests, "disliked_topics": []},
        "soul": {
            "core_traits": [],
            "cognitive_style": "",
            "values": [],
            "motivational_drivers": [],
            "current_phase": "",
            "life_stage": "",
            "deep_needs": [],
            "recent_awareness": [],
            "active_insights": [],
            "exploration_openness": 0.5,
            "source_platform_mix": [],
            "personality_portrait": spec.persona or "",
        },
    }
    return OnionProfile.from_dict(profile_dict)


def user_data_dir(base_dir: str | Path, user_id: str) -> Path:
    """Return the per-user data directory, creating it on demand."""
    safe_user_id = "".join(
        c if c.isalnum() or c in "-_." else "_" for c in user_id
    )
    p = Path(base_dir) / "users" / safe_user_id
    p.mkdir(parents=True, exist_ok=True)
    return p