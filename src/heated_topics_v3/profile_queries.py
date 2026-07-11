from heated_topics_v3.contracts import TopicQuery, UserProfile


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
