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