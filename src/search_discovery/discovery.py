from datetime import datetime, timezone, timedelta

from src.search_discovery.ranking import score_topic
from src.search_discovery.types import CandidateTopic, CreatorProfile, EnrichedContent, SearchResult


def cluster_results(
    profile: CreatorProfile,
    results: list[SearchResult],
    contents: list[EnrichedContent],
    source_weights: dict[str, int],
) -> list[CandidateTopic]:
    content_by_result_id = {content.result_id: content for content in contents}
    topics = []
    for index, result in enumerate(results, start=1):
        if result.fetch_status != "ok":
            continue
        content = content_by_result_id.get(result.result_id)
        text = " ".join([result.title, result.snippet, content.content if content else ""])
        matched_keywords = _matched_keywords(profile.all_keywords(), text)
        detail_level = content.content_quality if content is not None else "low"
        risk_level = _risk_level(text)
        source_hit = {
            "source_id": result.source_id,
            "title": result.title,
            "url": result.url,
            "content_type": result.content_type,
            "source_weight": source_weights.get(result.source_id, 0),
        }
        topic = CandidateTopic(
            topic_id=f"search_topic_{index:03d}",
            title=result.title,
            matched_keywords=matched_keywords,
            keyword_categories=[result.keyword_category],
            profile_match_score=_profile_match_score(matched_keywords, profile.all_keywords()),
            freshness="breaking" if result.published_at or "最新" in result.query else "ongoing",
            detail_level=detail_level,
            risk_level=risk_level,
            source_hits=[source_hit],
            summary=_summary(result, content),
            created_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        )
        topics.append(
            CandidateTopic(
                **{**topic.to_dict(), "topic_score": score_topic(topic)}
            )
        )
    return sorted(topics, key=lambda row: row.topic_score, reverse=True)


def _matched_keywords(keywords: list[str], text: str) -> list[str]:
    normalized = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in normalized]


def _profile_match_score(matched_keywords: list[str], all_keywords: list[str]) -> int:
    if not all_keywords:
        return 50
    return round(len(matched_keywords) / len(all_keywords) * 100)


def _risk_level(text: str) -> str:
    high_terms = ["案件", "违法", "未成年", "事故"]
    medium_terms = ["医疗", "投资", "监管", "争议", "辟谣"]
    if any(term in text for term in high_terms):
        return "high"
    if any(term in text for term in medium_terms):
        return "medium"
    return "low"


def _summary(result: SearchResult, content: EnrichedContent | None) -> str:
    detail = content.content if content is not None else result.snippet
    if detail:
        return detail[:160]
    return f"{result.title} 来自 {result.source_id}。"