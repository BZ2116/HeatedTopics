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
    grouped: dict[str, list[SearchResult]] = {}
    for result in results:
        if result.fetch_status != "ok":
            continue
        grouped.setdefault(_cluster_key(result), []).append(result)

    topics: list[CandidateTopic] = []
    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    for index, group in enumerate(grouped.values(), start=1):
        group_contents = [content_by_result_id[result.result_id] for result in group if result.result_id in content_by_result_id]
        text = " ".join(
            part
            for result in group
            for part in [result.title, result.snippet, content_by_result_id.get(result.result_id, _EMPTY_CONTENT).content]
            if part
        )
        matched_keywords = _matched_keywords(profile.all_keywords(), text)
        topic = CandidateTopic(
            topic_id=f"search_topic_{index:03d}",
            title=group[0].title,
            matched_keywords=matched_keywords,
            keyword_categories=_unique([result.keyword_category for result in group]),
            profile_match_score=_profile_match_score(matched_keywords, profile.all_keywords()),
            freshness="breaking" if any(result.published_at or "最新" in result.query for result in group) else "ongoing",
            detail_level=_best_detail_level(group_contents),
            risk_level=_risk_level(text),
            source_hits=_source_hits(group, source_weights),
            summary=_summary(group[0], group_contents),
            created_at=created_at,
        )
        topics.append(CandidateTopic(**{**topic.to_dict(), "topic_score": score_topic(topic)}))
    return sorted(topics, key=lambda row: row.topic_score, reverse=True)


def _cluster_key(result: SearchResult) -> str:
    if result.url:
        return result.url.rstrip("/").lower()
    return result.title.strip().lower()


def _matched_keywords(keywords: list[str], text: str) -> list[str]:
    normalized = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in normalized]


def _profile_match_score(matched_keywords: list[str], all_keywords: list[str]) -> int:
    if not all_keywords:
        return 50
    return round(len(matched_keywords) / len(all_keywords) * 100)


def _best_detail_level(contents: list[EnrichedContent]) -> str:
    order = {"low": 0, "medium": 1, "medium_high": 2, "high": 3}
    if not contents:
        return "low"
    return max((content.content_quality for content in contents), key=lambda level: order.get(level, 0))


def _risk_level(text: str) -> str:
    high_terms = ["案件", "违法", "未成年", "事故"]
    medium_terms = ["医疗", "投资", "监管", "争议", "辟谣"]
    if any(term in text for term in high_terms):
        return "high"
    if any(term in text for term in medium_terms):
        return "medium"
    return "low"


def _source_hits(results: list[SearchResult], source_weights: dict[str, int]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    seen = set()
    for result in results:
        key = (result.source_id, result.url)
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            {
                "source_id": result.source_id,
                "title": result.title,
                "url": result.url,
                "content_type": result.content_type,
                "source_weight": source_weights.get(result.source_id, 0),
            }
        )
    return hits


def _summary(result: SearchResult, contents: list[EnrichedContent]) -> str:
    for content in contents:
        if content.content:
            return content.content[:160]
    if result.snippet:
        return result.snippet[:160]
    return f"{result.title} 来自 {result.source_id}。"


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_EMPTY_CONTENT = EnrichedContent(result_id="", url="", title="", content="")
