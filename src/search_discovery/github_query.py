from datetime import date, timedelta

from src.search_discovery.types import CreatorProfile


def build_github_query(
    profile: CreatorProfile,
    *,
    today: date | None = None,
    min_stars: int = 200,
    days_since_update: int = 180,
    language: str = "",
) -> str:
    current_date = today or date.today()
    pushed_after = current_date - timedelta(days=days_since_update)
    keywords = _compact_keywords(profile, limit=5)
    parts = [
        keywords,
        "in:name,description,readme",
        f"stars:>{min_stars}",
        f"pushed:>{pushed_after.isoformat()}",
    ]
    if language.strip():
        parts.append(f"language:{language.strip()}")
    return " ".join(part for part in parts if part)


def _compact_keywords(profile: CreatorProfile, limit: int) -> str:
    values = profile.custom_keywords or profile.track_tags
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return " ".join(result)
