from src.search_discovery.discovery import cluster_results
from src.search_discovery.types import CreatorProfile, EnrichedContent, SearchResult


def test_cluster_results_groups_by_keyword_and_title_overlap():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent"],
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent GitHub",
            keyword_category="tech_project",
            title="AI Agent framework",
            url="https://github.com/example/agent",
            snippet="开源 agent framework",
            content_type="repo",
        )
    ]
    contents = [
        EnrichedContent(
            result_id="r1",
            url="https://github.com/example/agent",
            title="AI Agent framework",
            content="开源 agent framework",
            content_quality="high",
            evidence_confidence="high",
        )
    ]

    topics = cluster_results(profile, results, contents, source_weights={"github_search": 95})

    assert len(topics) == 1
    assert topics[0].matched_keywords == ["AI Agent"]
    assert topics[0].detail_level == "high"


def test_cluster_results_deduplicates_same_url_across_queries():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent", "MCP"],
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent in:name,description stars:>50",
            keyword_category="tech_project",
            title="example/agent-framework",
            url="https://github.com/example/agent-framework",
            snippet="AI Agent framework with MCP support",
            content_type="repo",
        ),
        SearchResult(
            result_id="r2",
            source_id="github_search",
            source_role="vertical_project",
            query="MCP in:name,description stars:>50",
            keyword_category="tech_tutorial",
            title="example/agent-framework",
            url="https://github.com/example/agent-framework",
            snippet="AI Agent framework with MCP support",
            content_type="repo",
        ),
    ]
    contents = [
        EnrichedContent(
            result_id="r1",
            url="https://github.com/example/agent-framework",
            title="example/agent-framework",
            content="AI Agent framework with MCP support",
            content_quality="high",
            evidence_confidence="high",
        ),
        EnrichedContent(
            result_id="r2",
            url="https://github.com/example/agent-framework",
            title="example/agent-framework",
            content="AI Agent framework with MCP support",
            content_quality="high",
            evidence_confidence="high",
        ),
    ]

    topics = cluster_results(profile, results, contents, source_weights={"github_search": 95})

    assert len(topics) == 1
    assert topics[0].keyword_categories == ["tech_project", "tech_tutorial"]
    assert topics[0].matched_keywords == ["AI Agent", "MCP"]
    assert len(topics[0].source_hits) == 1
