from src.core_pipeline.v3_hot_matrix.query_contract import UserProfile, build_topic_queries


def test_build_topic_queries_keeps_profile_context_for_hot_list_filtering():
    profile = UserProfile(
        profile_id="tech_ai_creator",
        display_name="Tech AI Creator",
        domains=("tech", "ai"),
        audience=("developers",),
        content_modes=("tutorial", "analysis"),
        preferred_platforms=("juejin", "bilibili", "baidu"),
        core_keywords=("AI Agent", "MCP", "RAG"),
        entity_keywords=("OpenAI", "Claude Code"),
        excluded_keywords=("celebrity gossip",),
    )

    queries = build_topic_queries(profile)

    assert [query.query_id for query in queries] == [
        "tech_ai_creator_q_001_core_hot",
        "tech_ai_creator_q_002_entity_hot",
    ]
    assert queries[0].query == "AI Agent MCP RAG"
    assert queries[0].target_platforms == ("juejin", "bilibili", "baidu")
    assert queries[0].usage == "filter_and_enrich_hot_lists"
    assert queries[1].query == "OpenAI Claude Code"
    assert queries[1].profile_id == "tech_ai_creator"
