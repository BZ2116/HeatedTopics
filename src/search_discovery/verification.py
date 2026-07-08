from dataclasses import dataclass

from src.search_discovery.types import EnrichedContent, SearchResult


@dataclass(frozen=True)
class VerificationAssessment:
    verification_score: int
    evidence_level: str
    source_count: int
    has_official_source: bool
    has_news_media_source: bool
    has_clear_publish_time: bool
    single_source: bool
    risk_flags: list[str]
    verification_notes: list[str]


NEWS_SOURCE_IDS = {"tianapi_news", "news_api_cn"}
OFFICIAL_TERMS = ["官方", "公告", "通报", "回应", "发布"]
RUMOR_TERMS = ["网传", "曝", "爆料", "内幕", "小道消息", "稳赚"]
HIGH_RISK_TERMS = ["医疗", "投资", "事故", "案件", "未成年", "违法"]


def assess_topic_verification(
    results: list[SearchResult],
    contents: list[EnrichedContent],
    *,
    text: str,
) -> VerificationAssessment:
    source_ids = {result.source_id for result in results if result.source_id}
    source_count = len(source_ids)
    has_news_media_source = any(result.source_id in NEWS_SOURCE_IDS or result.content_type == "news" for result in results)
    has_official_source = _contains_any(text, OFFICIAL_TERMS)
    has_clear_publish_time = any(result.published_at for result in results) or any(content.published_at for content in contents)
    single_source = source_count <= 1
    risk_flags = _risk_flags(text)
    score = 35
    score += min(source_count, 3) * 15
    if has_news_media_source:
        score += 15
    if has_official_source:
        score += 10
    if has_clear_publish_time:
        score += 10
    if single_source:
        score -= 25
    if any(result.content_type == "search_snippet" for result in results):
        score -= 10
    if risk_flags:
        score -= 20
    score = max(0, min(100, score))
    return VerificationAssessment(
        verification_score=score,
        evidence_level=_evidence_level(score),
        source_count=source_count,
        has_official_source=has_official_source,
        has_news_media_source=has_news_media_source,
        has_clear_publish_time=has_clear_publish_time,
        single_source=single_source,
        risk_flags=risk_flags,
        verification_notes=_verification_notes(source_count, has_clear_publish_time, risk_flags),
    )


def _risk_flags(text: str) -> list[str]:
    flags: list[str] = []
    if _contains_any(text, RUMOR_TERMS):
        flags.append("包含传闻或夸张表达，不能直接当作事实。")
    if _contains_any(text, HIGH_RISK_TERMS):
        flags.append("包含高风险主题，发布前需要人工核验关键事实。")
    return flags


def _verification_notes(source_count: int, has_clear_publish_time: bool, risk_flags: list[str]) -> list[str]:
    notes: list[str] = []
    if source_count <= 1:
        notes.append("单一来源支撑，建议补充独立来源。")
    else:
        notes.append("多个独立来源指向同一话题，基础可信度较高。")
    if not has_clear_publish_time:
        notes.append("缺少明确发布时间，需复核时效性。")
    notes.extend(risk_flags)
    return notes


def _evidence_level(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 55:
        return "medium"
    return "weak"


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)
