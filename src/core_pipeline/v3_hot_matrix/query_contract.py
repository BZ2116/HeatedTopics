from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    display_name: str
    domains: tuple[str, ...]
    audience: tuple[str, ...]
    content_modes: tuple[str, ...]
    preferred_platforms: tuple[str, ...]
    core_keywords: tuple[str, ...]
    entity_keywords: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopicQuery:
    query_id: str
    profile_id: str
    query: str
    intent: str
    target_platforms: tuple[str, ...]
    keywords: tuple[str, ...]
    usage: str
    priority: int


def build_topic_queries(profile: UserProfile) -> list[TopicQuery]:
    queries: list[TopicQuery] = []
    if profile.core_keywords:
        queries.append(
            TopicQuery(
                query_id=f"{profile.profile_id}_q_001_core_hot",
                profile_id=profile.profile_id,
                query=" ".join(profile.core_keywords),
                intent="profile_core_hot",
                target_platforms=profile.preferred_platforms,
                keywords=profile.core_keywords,
                usage="filter_and_enrich_hot_lists",
                priority=100,
            )
        )
    if profile.entity_keywords:
        queries.append(
            TopicQuery(
                query_id=f"{profile.profile_id}_q_002_entity_hot",
                profile_id=profile.profile_id,
                query=" ".join(profile.entity_keywords),
                intent="profile_entity_hot",
                target_platforms=profile.preferred_platforms,
                keywords=profile.entity_keywords,
                usage="filter_and_enrich_hot_lists",
                priority=80,
            )
        )
    return queries
