from src.search_discovery.ranking import score_topic
from src.search_discovery.types import CandidateTopic


def test_score_topic_rewards_detail_and_source_weight():
    topic = CandidateTopic(
        topic_id="topic_001",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=90,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[{"source_weight": 95}, {"source_weight": 80}],
        summary="有多个来源。",
    )

    assert score_topic(topic) >= 80


def test_score_topic_penalizes_sensitive_risk():
    low_risk = CandidateTopic(
        topic_id="topic_low",
        title="AI Agent 开源项目升温",
        matched_keywords=["AI Agent"],
        keyword_categories=["tech_project"],
        profile_match_score=90,
        freshness="breaking",
        detail_level="high",
        risk_level="low",
        source_hits=[{"source_weight": 95}],
        summary="低风险。",
    )
    high_risk = CandidateTopic(
        topic_id="topic_high",
        title="投资医疗争议事件",
        matched_keywords=["投资"],
        keyword_categories=["risk_sensitive"],
        profile_match_score=90,
        freshness="breaking",
        detail_level="high",
        risk_level="high",
        source_hits=[{"source_weight": 95}],
        summary="高风险。",
    )

    assert score_topic(low_risk) > score_topic(high_risk)