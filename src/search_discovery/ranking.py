from src.search_discovery.types import CandidateTopic


def score_topic(topic: CandidateTopic) -> int:
    source_score = _avg_source_weight(topic)
    profile_keyword_score = topic.profile_match_score
    detail_score = {"high": 95, "medium_high": 85, "medium": 70, "low": 25}.get(topic.detail_level, 40)
    freshness_score = {"breaking": 95, "ongoing": 80, "evergreen": 60, "fading": 30}.get(topic.freshness, 50)
    evidence_diversity_score = min(len(topic.source_hits), 4) * 25
    risk_penalty = {"low": 0, "medium": 30, "high": 70}.get(topic.risk_level, 20)
    score = (
        source_score * 0.25
        + profile_keyword_score * 0.25
        + detail_score * 0.20
        + freshness_score * 0.15
        + evidence_diversity_score * 0.10
        - risk_penalty * 0.05
    )
    return max(0, min(100, round(score)))


def _avg_source_weight(topic: CandidateTopic) -> float:
    weights = [
        int(hit.get("source_weight", 0))
        for hit in topic.source_hits
        if isinstance(hit.get("source_weight", 0), int)
    ]
    if not weights:
        return 0
    return sum(weights) / len(weights)