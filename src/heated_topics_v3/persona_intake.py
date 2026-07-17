"""Single-user persona intake.

`register_persona` is the importable entry point the integrating project
calls to onboard one new user in a single step:

    raw persona text
        -> structure (LLM, heuristic fallback)   PersonaPersonal
        -> derive core_keywords                  tuple[str, ...]
        -> allocate user_id                      {slug}_{NNN}
        -> write config/profiles/{user_id}.json
        -> load back through the v2 validator     PersonaProfile
        -> pre-warm LLM keyword cache             ExtractedKeyword[]

Structuring falls back to the heuristic splitter when the LLM is down or
returns junk (same policy as the xlsx batch script). Keyword extraction is
delegated to `extract_persona_keywords`, which already degrades to
core_keywords on LLM failure, so registration never fails on a flaky LLM.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from heated_topics_v3.contracts import (
    ExtractedKeyword,
    PersonaPersonal,
    PersonaProfile,
)
from heated_topics_v3.llm_client import LLMUnavailable
from heated_topics_v3.llm_keywords import extract_persona_keywords
from heated_topics_v3.persona_slugs import FALLBACK_KEYWORDS, assign_user_id
from heated_topics_v3.persona_structurer import (
    PersonaStructureError,
    _split_heuristic,
    extract_short_keywords,
    structure_persona,
)
from heated_topics_v3.profile_loader import load_persona_profile

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_DIR = _REPO_ROOT / "config" / "profiles"
DEFAULT_KEYWORD_CACHE_DIR = _REPO_ROOT / "cache" / "core_keywords"


@dataclass(frozen=True)
class RegisteredPersona:
    user_id: str
    profile_path: Path
    profile: PersonaProfile
    keywords: tuple[ExtractedKeyword, ...]


def register_persona(
    level1: str,
    level2: str,
    persona_text: str,
    *,
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
    keyword_cache_dir: str | Path = DEFAULT_KEYWORD_CACHE_DIR,
    core_keywords: Sequence[str] | None = None,
    use_llm: bool = True,
    structurer_llm: Callable[..., str] | None = None,
    keyword_llm: Callable[..., str] | None = None,
) -> RegisteredPersona:
    """Onboard one new user: structure, persist, and pre-warm keywords.

    Raises `ValueError` if any of level1/level2/persona_text is blank.
    """
    level1 = (level1 or "").strip()
    level2 = (level2 or "").strip()
    persona_text = (persona_text or "").strip()
    if not level1 or not level2 or not persona_text:
        raise ValueError("level1, level2 and persona_text must all be non-empty")

    profiles_dir = Path(profiles_dir)

    personal = _build_personal(
        level1, level2, persona_text, use_llm=use_llm, llm=structurer_llm
    )
    core = _derive_core_keywords(level1, level2, persona_text, core_keywords)
    user_id = assign_user_id(level2, profiles_dir)

    profiles_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_id": user_id,
        "level1": level1,
        "level2": level2,
        "personal": {
            "role": personal.role,
            "subject": personal.subject,
            "scenarios": list(personal.scenarios),
            "value": personal.value,
        },
        "core_keywords": list(core),
    }
    profile_path = profiles_dir / f"{user_id}.json"
    profile_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Load back through the v2 validator: catches any malformed output here
    # rather than deep inside a later pipeline run.
    profile = load_persona_profile(profile_path)

    extraction = extract_persona_keywords(
        profile,
        cache_dir=keyword_cache_dir,
        llm=keyword_llm,
        allow_llm=use_llm,
    )
    return RegisteredPersona(
        user_id=user_id,
        profile_path=profile_path,
        profile=profile,
        keywords=extraction.keywords,
    )


def _build_personal(
    level1: str,
    level2: str,
    persona_text: str,
    *,
    use_llm: bool,
    llm: Callable[..., str] | None,
) -> PersonaPersonal:
    if use_llm:
        try:
            return structure_persona(level1, level2, persona_text, llm=llm)
        except (LLMUnavailable, PersonaStructureError):
            return _heuristic_personal(level1, level2, persona_text)
    return _heuristic_personal(level1, level2, persona_text)


def _heuristic_personal(
    level1: str, level2: str, persona_text: str
) -> PersonaPersonal:
    """LLM-free PersonaPersonal, backfilled from level1/level2/fallbacks."""
    role, subject, scenarios, value = _split_heuristic(persona_text)
    if not role:
        role = level1
    if not subject:
        subject = level2
    if not value:
        value = f"围绕{level2}分享"
    if not scenarios:
        scenarios = list(FALLBACK_KEYWORDS.get(level2, [level2]))
    return PersonaPersonal(
        role=role,
        subject=subject,
        scenarios=tuple(scenarios[:6]),
        value=value,
    )


def _derive_core_keywords(
    level1: str,
    level2: str,
    persona_text: str,
    override: Sequence[str] | None,
) -> tuple[str, ...]:
    """Caller override wins; else heuristic short keywords; else fallback list."""
    if override is not None:
        cleaned = tuple(str(k).strip() for k in override if str(k).strip())
        if cleaned:
            return cleaned
    derived = tuple(extract_short_keywords(level1, level2, persona_text))
    if derived:
        return derived
    fallback = tuple(FALLBACK_KEYWORDS.get(level2, [level2]))
    return fallback or (level2,)
