"""Load users.json and build OpenBiliClaw profile objects.

Pipeline:
  load_users()   ->  list[UserSpec]
  UserSpec       ->  OnionProfile (via build_onion_profile())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openbiliclaw.soul.profile import (
    OnionProfile,
)

from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError


@dataclass
class InterestSpec:
    name: str
    category: str
    weight: float


@dataclass
class StyleSpec:
    reading_depth: str = "medium"
    tone_preference: str = "neutral"


@dataclass
class ContextSpec:
    primary_scene: str = "general"
    device: str = "desktop"


@dataclass
class UserSpec:
    user_id: str
    display_name: str
    interests: list[InterestSpec]
    disliked_topics: list[str] = field(default_factory=list)
    style: StyleSpec = field(default_factory=StyleSpec)
    context: ContextSpec = field(default_factory=ContextSpec)
    exploration_openness: float = 0.5
    favorite_up_users: list[str] = field(default_factory=list)
    source_platform_mix: dict[str, float] = field(default_factory=dict)
    core_traits: list[str] = field(default_factory=list)
    deep_needs: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    life_stage: str = ""
    current_phase: str = ""
    cognitive_style: list[str] = field(default_factory=list)
    recent_awareness: list[dict[str, Any]] = field(default_factory=list)
    active_insights: list[dict[str, Any]] = field(default_factory=list)


def _parse_one_user(raw: dict[str, Any]) -> UserSpec:
    if "user_id" not in raw or not str(raw["user_id"]).strip():
        raise ProfileValidationError(f"user missing 'user_id': keys={list(raw.keys())}")
    interests_raw = raw.get("interests", [])
    if not interests_raw:
        raise ProfileValidationError(f"user {raw['user_id']!r} has empty 'interests'")
    interests: list[InterestSpec] = []
    for i, item in enumerate(interests_raw):
        if not isinstance(item, dict):
            raise ProfileValidationError(
                f"user {raw['user_id']!r} interest[{i}] not a dict: {item!r}"
            )
        weight = float(item.get("weight", 0.5))
        if not (0.0 <= weight <= 1.0):
            raise ProfileValidationError(
                f"user {raw['user_id']!r} interest[{i}].weight={weight} not in [0,1]"
            )
        interests.append(
            InterestSpec(
                name=str(item["name"]),
                category=str(item.get("category", item["name"])),
                weight=weight,
            )
        )
    style_raw = raw.get("style") or {}
    context_raw = raw.get("context") or {}
    return UserSpec(
        user_id=str(raw["user_id"]),
        display_name=str(raw.get("display_name", raw["user_id"])),
        interests=interests,
        disliked_topics=list(raw.get("disliked_topics", [])),
        style=StyleSpec(
            reading_depth=str(style_raw.get("reading_depth", "medium")),
            tone_preference=str(style_raw.get("tone_preference", "neutral")),
        ),
        context=ContextSpec(
            primary_scene=str(context_raw.get("primary_scene", "general")),
            device=str(context_raw.get("device", "desktop")),
        ),
        exploration_openness=float(raw.get("exploration_openness", 0.5)),
        favorite_up_users=list(raw.get("favorite_up_users", [])),
        source_platform_mix=dict(raw.get("source_platform_mix", {})),
        core_traits=list(raw.get("core_traits", [])),
        deep_needs=list(raw.get("deep_needs", [])),
        values=list(raw.get("values", [])),
        life_stage=str(raw.get("life_stage", "")),
        current_phase=str(raw.get("current_phase", "")),
        cognitive_style=list(raw.get("cognitive_style", [])),
        recent_awareness=list(raw.get("recent_awareness", [])),
        active_insights=list(raw.get("active_insights", [])),
    )


def load_users(path: str | Path) -> list[UserSpec]:
    """Load and validate users.json. Raises on any error.

    Raises:
        FileNotFoundError: file does not exist
        json.JSONDecodeError: file is not valid JSON
        ProfileValidationError: schema invalid
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"users.json not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "users" not in raw:
        raise ProfileValidationError(
            f"top-level key 'users' missing in {p}; got keys={list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__}"
        )
    if not isinstance(raw["users"], list):
        raise ProfileValidationError(f"'users' must be a list in {p}")
    return [_parse_one_user(item) for item in raw["users"]]


def build_onion_profile(spec: UserSpec) -> OnionProfile:
    """Build an OpenBiliClaw OnionProfile from a UserSpec.

    Uses populate_from_flat_preference() for the preference layer; assigns
    onion layers directly; passes awareness/insight through from_dict.
    """
    preference_data: dict[str, Any] = {
        "interests": [
            {
                "name": i.name,
                "category": i.category,
                "weight": i.weight,
            }
            for i in spec.interests
        ],
        "disliked_topics": list(spec.disliked_topics),
        "exploration_openness": spec.exploration_openness,
        "favorite_up_users": list(spec.favorite_up_users),
        "source_platform_mix": dict(spec.source_platform_mix),
        "style": {
            "reading_depth": spec.style.reading_depth,
            "tone_preference": spec.style.tone_preference,
        },
        "context": {
            "primary_scene": spec.context.primary_scene,
            "device": spec.context.device,
        },
    }
    soul_dict: dict[str, Any] = {
        "core": {
            "core_traits": list(spec.core_traits),
            "deep_needs": list(spec.deep_needs),
        },
        "values_layer": {
            "values": list(spec.values),
            "motivational_drivers": [],
        },
        "interest": {
            "likes": [],
            "dislikes": [],
            "favorite_up_users": list(spec.favorite_up_users),
        },
        "role": {
            "life_stage": spec.life_stage,
            "current_phase": spec.current_phase,
        },
        "surface": {
            "cognitive_style": list(spec.cognitive_style),
            "exploration_openness": spec.exploration_openness,
            "style": {
                "reading_depth": spec.style.reading_depth,
                "tone_preference": spec.style.tone_preference,
            },
            "context": {
                "primary_scene": spec.context.primary_scene,
                "device": spec.context.device,
            },
        },
        "personality_portrait": "",
        "recent_awareness": list(spec.recent_awareness),
        "active_insights": list(spec.active_insights),
        "source_platform_mix": dict(spec.source_platform_mix),
        "version": 2,
    }
    profile = OnionProfile.from_dict(soul_dict)
    profile.populate_from_flat_preference(preference_data)
    return profile


def user_data_dir(base_dir: str | Path, user_id: str) -> Path:
    """Return the per-user data directory, creating it on demand."""
    safe_user_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_id)
    p = Path(base_dir) / "users" / safe_user_id
    p.mkdir(parents=True, exist_ok=True)
    return p
