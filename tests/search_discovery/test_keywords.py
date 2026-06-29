from src.search_discovery.keywords import classify_keywords, generate_query_bundles
from src.search_discovery.types import CreatorProfile


def test_classify_tech_profile_adds_project_and_tutorial_categories():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        track_tags=["AI", "开发者工具", "开源项目"],
        custom_keywords=["AI Agent", "MCP"],
        content_modes=["教程实践"],
    )

    categories = classify_keywords(profile)

    assert "topic_discovery" in categories
    assert "tech_project" in categories
    assert "tech_tutorial" in categories


def test_generate_query_bundles_uses_category_templates():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent"],
    )

    bundles = generate_query_bundles(profile, categories=["topic_discovery", "tech_project"])

    by_category = {bundle.category: bundle.queries for bundle in bundles}
    assert "AI Agent 最新进展" in by_category["topic_discovery"]
    assert "AI Agent in:name,description stars:>50 pushed:>2025-01-01" in by_category["tech_project"]


def test_generate_query_bundles_prioritizes_custom_keywords_over_track_tags():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        track_tags=["AI", "开发者工具", "开源项目"],
        custom_keywords=["AI Agent", "MCP", "RAG"],
        content_modes=["教程实践"],
    )

    bundles = generate_query_bundles(profile, categories=["tech_project"], max_queries_per_category=6)

    queries = bundles[0].queries
    assert any(query.startswith("AI Agent ") for query in queries)
    assert any(query.startswith("MCP ") for query in queries)
    assert any(query.startswith("RAG ") for query in queries)
    assert not any(query == "AI GitHub" for query in queries)


def test_generate_query_bundles_round_robins_templates_across_keywords():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent", "MCP", "RAG"],
    )

    bundles = generate_query_bundles(profile, categories=["topic_discovery"], max_queries_per_category=6)

    assert bundles[0].queries == [
        "AI Agent 最新进展",
        "MCP 最新进展",
        "RAG 最新进展",
        "AI Agent 热点",
        "MCP 热点",
        "RAG 热点",
    ]
