"""Profile v2 loader and validator.

Schema (v2):
    {
      "user_id": "zhao_001",
      "level1": "科技AI",
      "level2": "AI工具应用",
      "personal": {
        "role": "...",
        "subject": "...",
        "scenarios": ["...", "..."],
        "value": "..."
      },
      "core_keywords": ["..."]
    }
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from heated_topics_v3.contracts import PersonaPersonal, PersonaProfile


class ProfileSchemaError(ValueError):
    """Raised when a profile file fails v2 schema validation."""


_LEGACY_KEYS: tuple[str, ...] = (
    "display_name",
    "domains",
    "audience",
    "content_modes",
    "preferred_platforms",
    "entity_keywords",
)

_V2_REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "user_id",
    "level1",
    "level2",
    "personal",
    "core_keywords",
)

_V2_REQUIRED_PERSONAL: tuple[str, ...] = ("role", "subject", "scenarios", "value")


def load_persona_profile(path: str | Path) -> PersonaProfile:
    """Load and validate a v2 profile. Raises ProfileSchemaError on bad input."""
    profile_path = Path(path)
    payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ProfileSchemaError(f"profile root must be an object, got {type(payload).__name__}")

    if is_legacy_profile_payload(payload):
        offending = sorted(k for k in _LEGACY_KEYS if k in payload)
        raise ProfileSchemaError(
            "profile uses legacy v1 schema (found keys: "
            f"{', '.join(offending) or '<none>'}); migrate to v2 with user_id/"
            "level1/level2/personal{role,subject,scenarios,value}/core_keywords"
        )

    missing_top = [k for k in _V2_REQUIRED_TOP_LEVEL if k not in payload]
    if missing_top:
        raise ProfileSchemaError(f"missing required v2 fields: {', '.join(missing_top)}")

    user_id = str(payload["user_id"]).strip()
    level1 = str(payload["level1"]).strip()
    level2 = str(payload["level2"]).strip()
    if not user_id:
        raise ProfileSchemaError("user_id is empty")
    if not level1:
        raise ProfileSchemaError("level1 is empty")
    if not level2:
        raise ProfileSchemaError("level2 is empty")

    personal_raw = payload["personal"]
    if not isinstance(personal_raw, dict):
        raise ProfileSchemaError(f"personal must be an object, got {type(personal_raw).__name__}")
    missing_personal = [k for k in _V2_REQUIRED_PERSONAL if k not in personal_raw]
    if missing_personal:
        raise ProfileSchemaError(f"personal missing fields: {', '.join(missing_personal)}")

    role = str(personal_raw["role"]).strip()
    subject = str(personal_raw["subject"]).strip()
    scenarios_raw = personal_raw["scenarios"]
    if not isinstance(scenarios_raw, list):
        raise ProfileSchemaError(f"personal.scenarios must be a list, got {type(scenarios_raw).__name__}")
    scenarios = tuple(str(s).strip() for s in scenarios_raw if str(s).strip())
    if not scenarios:
        raise ProfileSchemaError("personal.scenarios is empty")
    value = str(personal_raw["value"]).strip()
    if not role or not subject or not value:
        raise ProfileSchemaError("personal.role / personal.subject / personal.value must be non-empty")

    core_keywords_raw = payload["core_keywords"]
    if not isinstance(core_keywords_raw, list):
        raise ProfileSchemaError(
            f"core_keywords must be a list, got {type(core_keywords_raw).__name__}"
        )
    core_keywords = tuple(str(k).strip() for k in core_keywords_raw if str(k).strip())
    if not core_keywords:
        raise ProfileSchemaError("core_keywords is empty (must list at least one fallback search term)")

    personal = PersonaPersonal(
        role=role, subject=subject, scenarios=scenarios, value=value,
    )
    signature = compute_persona_signature(level1, level2, personal)

    return PersonaProfile(
        user_id=user_id,
        level1=level1,
        level2=level2,
        personal=personal,
        core_keywords=core_keywords,
        persona_signature=signature,
    )


def is_legacy_profile(path: str | Path) -> bool:
    """Quick check whether a profile file uses the legacy v1 schema."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return is_legacy_profile_payload(payload)


def is_legacy_profile_payload(payload: dict) -> bool:
    """Heuristic: legacy v1 profiles have display_name/domains/audience without v2 keys."""
    has_legacy_marker = any(k in payload for k in _LEGACY_KEYS)
    has_v2_marker = all(k in payload for k in ("user_id", "level1", "level2", "personal"))
    return has_legacy_marker and not has_v2_marker


def compute_persona_signature(
    level1: str, level2: str, personal: PersonaPersonal,
) -> str:
    """Stable hash of the persona-defining fields. Used to invalidate keyword cache."""
    canonical = json.dumps(
        {
            "level1": level1,
            "level2": level2,
            "role": personal.role,
            "subject": personal.subject,
            "scenarios": list(personal.scenarios),
            "value": personal.value,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]