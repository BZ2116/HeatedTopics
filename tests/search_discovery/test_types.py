from src.search_discovery.types import CandidateTopic, CreatorProfile, SearchResult


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