from src.search_discovery.types import CandidateTopic, CreatorProfile, SearchResult, SearchRoute


def test_creator_profile_from_dict_uses_empty_defaults():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "custom_keywords": ["AI Agent"],
        }
    )

    assert profile.creator_id == "creator_001"
    assert profile.track_tags == []
    assert profile.content_modes == []


def test_search_result_rejects_title_only_result():
    result = SearchResult(
        result_id="r1",
        source_id="mock",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        title="只有标题",
    )

    assert result.has_usable_detail() is False


def test_candidate_topic_serializes_source_hits():
    topic = CandidateTopic(
        topic_id="topic_001",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=88,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[
            {
                "source_id": "github_search",
                "title": "example/agent",
                "url": "https://github.com/example/agent",
                "content_type": "repo",
                "source_weight": 95,
            }
        ],
        summary="GitHub 和文章结果共同指向该话题。",
    )

    row = topic.to_dict()

    assert row["topic_id"] == "topic_001"
    assert row["source_hits"][0]["source_id"] == "github_search"


def test_creator_profile_accepts_new_request_fields():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "platforms": ["小红书", "公众号"],
            "track_tags": ["AI", "开源项目"],
            "custom_keywords": ["AI Agent", "MCP", "RAG"],
            "content_goal": "寻找近期技术趋势",
            "exclude_keywords": ["纯营销"],
        }
    )

    assert profile.platforms == ["小红书", "公众号"]
    assert profile.content_goal == "寻找近期技术趋势"
    assert profile.exclude_keywords == ["纯营销"]
    assert profile.all_keywords() == ["AI", "开源项目", "AI Agent", "MCP", "RAG"]


def test_search_route_serializes_profile_specific_query():
    route = SearchRoute(
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
        intent="tech_project",
        weight=100,
        reason="科技类创作者关注开源项目，GitHub 适合召回 repo。",
    )

    assert route.to_dict()["source_id"] == "github_search"
    assert route.to_dict()["query"].startswith("AI Agent MCP RAG")
    assert route.to_dict()["weight"] == 100


def test_search_result_keeps_route_metadata():
    result = SearchResult(
        result_id="r1",
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
        keyword_category="tech_project",
        title="example/agent-framework",
        url="https://github.com/example/agent-framework",
        snippet="Agent framework",
        route_weight=100,
        route_reason="GitHub is preferred for tech project discovery.",
        matched_keywords=["AI Agent"],
    )

    row = result.to_dict()
    assert row["route_weight"] == 100
    assert row["route_reason"] == "GitHub is preferred for tech project discovery."
    assert row["matched_keywords"] == ["AI Agent"]