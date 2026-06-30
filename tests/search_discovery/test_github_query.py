from datetime import date

from src.search_discovery.github_query import build_github_query
from src.search_discovery.types import CreatorProfile


def test_build_github_query_uses_custom_keywords_and_hunter_filters():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "track_tags": ["AI", "开发者工具", "开源项目"],
            "custom_keywords": ["AI Agent", "MCP", "RAG"],
        }
    )

    query = build_github_query(profile, today=date(2026, 6, 29), min_stars=200, days_since_update=180)

    assert query == (
        "AI Agent MCP RAG in:name,description,readme "
        "stars:>200 pushed:>2025-12-31"
    )


def test_build_github_query_accepts_language_filter():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "开发者博主",
            "profile_type": "developer_creator",
            "custom_keywords": ["agent framework"],
        }
    )

    query = build_github_query(
        profile,
        today=date(2026, 6, 29),
        min_stars=50,
        days_since_update=30,
        language="Python",
    )

    assert query == (
        "agent framework in:name,description,readme "
        "stars:>50 pushed:>2026-05-30 language:Python"
    )


def test_build_github_query_limits_keywords_to_keep_query_focused():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "custom_keywords": ["AI Agent", "MCP", "RAG", "workflow", "tools", "memory"],
        }
    )

    query = build_github_query(profile, today=date(2026, 6, 29), min_stars=200, days_since_update=180)

    assert query.startswith("AI Agent MCP RAG workflow tools ")
    assert "memory" not in query
