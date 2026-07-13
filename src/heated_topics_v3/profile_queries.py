"""Compact Qianfan web-search query construction."""

from heated_topics_v3.contracts import UserProfile


MAX_QIANFAN_QUERY_UNITS = 72


def qianfan_query_units(value: str) -> int:
    """Count ASCII characters as one API unit and non-ASCII as two."""
    return sum(1 if character.isascii() else 2 for character in value)


def _compact_persona_token(persona: str) -> str:
    token = persona.strip()
    if token.startswith("面向"):
        token = token.removeprefix("面向").split("的", 1)[0]
    return token[:8]


def _truncate_to_units(value: str, limit: int) -> str:
    units = 0
    characters: list[str] = []
    for character in value:
        character_units = 1 if character.isascii() else 2
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
    tokens = list(dict.fromkeys(token for token in candidates if token))
    return _truncate_to_units(" ".join(tokens), MAX_QIANFAN_QUERY_UNITS)
