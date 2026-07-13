"""Compact Qianfan web-search query construction."""

from heated_topics_v3.contracts import UserProfile


MAX_QIANFAN_QUERY_UNITS = 72
COMPONENT_UNIT_LIMITS = (24, 20, 16, 8)


def _character_units(character: str) -> int:
    """Use one unit for ASCII and two for CJK or any other Unicode.

    Treating all non-ASCII characters like CJK is deterministic and
    conservative for the upstream query limit.
    """
    if character.isascii():
        return 1
    codepoint = ord(character)
    if 0x3400 <= codepoint <= 0x4DBF or 0x4E00 <= codepoint <= 0x9FFF:
        return 2
    return 2


def qianfan_query_units(value: str) -> int:
    """Count ASCII as one unit and all non-ASCII conservatively as two."""
    return sum(_character_units(character) for character in value)


def _compact_persona_token(persona: str) -> str:
    token = persona.strip()
    if token.startswith("面向"):
        token = token.removeprefix("面向").split("的", 1)[0]
    return token[:8]


def _truncate_to_units(value: str, limit: int) -> str:
    units = 0
    characters: list[str] = []
    for character in value:
        character_units = _character_units(character)
        if units + character_units > limit:
            break
        characters.append(character)
        units += character_units
    return "".join(characters).rstrip()


def build_qianfan_query(profile: UserProfile) -> str:
    """Build a deduplicated profile-derived query within Qianfan's limit."""
    candidates = (
        profile.primary_keyword.strip(),
        profile.secondary_track.strip(),
        _compact_persona_token(profile.persona),
        "最新热点",
    )
    compact_candidates = (
        _truncate_to_units(token, limit)
        for token, limit in zip(candidates, COMPONENT_UNIT_LIMITS)
    )
    tokens = list(dict.fromkeys(token for token in compact_candidates if token))
    query = " ".join(tokens)
    if qianfan_query_units(query) > MAX_QIANFAN_QUERY_UNITS:
        raise AssertionError("Qianfan component budgets exceeded query limit")
    return query
