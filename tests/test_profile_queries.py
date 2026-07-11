from heated_topics_v3.contracts import UserProfile
from heated_topics_v3.profile_queries import build_topic_queries


def test_profile_generates_queries_for_hot_list_filtering():
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

    assert queries[0].query == "AI Agent MCP RAG"
    assert queries[0].usage == "filter_and_enrich_hot_lists"
    assert queries[1].query == "OpenAI Claude Code"
