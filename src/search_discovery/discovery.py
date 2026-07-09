import urllib.parse
import json
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone, timedelta

from src.search_discovery.query_intelligence import matched_terms, score_text_match, split_user_terms
from src.search_discovery.ranking import score_topic
from src.search_discovery.source_labels import search_engine_name
from src.search_discovery.topic_quality import topic_result_candidate
from src.search_discovery.types import CandidateTopic, CreatorProfile, EnrichedContent, SearchResult
from src.search_discovery.verification import assess_topic_verification


def cluster_results(
    profile: CreatorProfile,
    results: list[SearchResult],
    contents: list[EnrichedContent],
    source_weights: dict[str, int],
    max_age_days: int = 90,
) -> list[CandidateTopic]:
    content_by_result_id = {content.result_id: content for content in contents}
    structured_terms = split_user_terms(profile)
    grouped: dict[str, list[SearchResult]] = {}
    for result in results:
        if result.fetch_status != "ok":
            continue
        # Translate English title/snippet to Chinese before quality checks
        translated_result = result
        if not _has_chinese(result.title):
            zh_title = _translate_en_to_zh(result.title)
            zh_snippet = _translate_en_to_zh(result.snippet)
            translated_result = replace(result, title=zh_title, snippet=zh_snippet)
        candidate = topic_result_candidate(profile, translated_result)
        if candidate is None:
            continue
        if not _is_recent_enough(candidate, max_age_days=max_age_days):
            continue
        grouped.setdefault(_cluster_key(candidate), []).append(candidate)

    # Second-pass: merge clusters with the same normalized title
    title_groups: dict[str, list[SearchResult]] = {}
    for cluster in grouped.values():
        title_key = _title_normalized(cluster[0])
        title_groups.setdefault(title_key, []).extend(cluster)

    topics: list[CandidateTopic] = []
    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    for index, group in enumerate(title_groups.values(), start=1):
        group_contents = [content_by_result_id[result.result_id] for result in group if result.result_id in content_by_result_id]
        text = " ".join(
            part
            for result in group
            for part in [result.title, result.snippet, content_by_result_id.get(result.result_id, _EMPTY_CONTENT).content]
            if part
        )
        matched_keywords = matched_terms(structured_terms, title=group[0].title, snippet=" ".join(result.snippet for result in group), content=text)
        match_score = score_text_match(structured_terms, title=group[0].title, snippet=" ".join(result.snippet for result in group), content=text)
        verification = assess_topic_verification(group, group_contents, text=text)
        topic = CandidateTopic(
            topic_id=f"search_topic_{index:03d}",
            title=group[0].title,
            matched_keywords=matched_keywords,
            keyword_categories=_unique([result.keyword_category for result in group]),
            profile_match_score=match_score or _profile_match_score(matched_keywords, profile.all_keywords()),
            freshness="breaking" if any(result.published_at or "最新" in result.query for result in group) else "ongoing",
            detail_level=_best_detail_level(group_contents),
            risk_level=_risk_level(text),
            source_hits=_source_hits(group, source_weights),
            summary=_summary(group[0], group_contents),
            created_at=created_at,
            verification_score=verification.verification_score,
            evidence_level=verification.evidence_level,
            verification_notes=verification.verification_notes,
            risk_flags=verification.risk_flags,
        )
        topics.append(CandidateTopic(**{**topic.to_dict(), "topic_score": score_topic(topic)}))
    return sorted(topics, key=lambda row: row.topic_score, reverse=True)


def _cluster_key(result: SearchResult) -> str:
    if result.url:
        url = result.url.rstrip("/").lower()
        url = _strip_tracking_params(url)
        return url
    return result.title.strip().lower()


def _strip_tracking_params(url: str) -> str:
    url = url.split("?")[0]
    url = url.split("#")[0]
    for param in ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "spm", "scm", "share"]:
        url = url.replace(f"&{param}=%", f"&{param}=").replace(f"?{param}=%", f"?{param}=")
    return url


def _title_normalized(result: SearchResult) -> str:
    """Normalized title for cross-domain duplicate detection."""
    title = result.title.strip().lower()
    for suffix in ["_网易", "_腾讯新闻", "_新浪", "_凤凰网", "_百家号", "_知乎", "_微博"]:
        title = title.rsplit(suffix, 1)[0]
    title = title.strip("，。！?？、:：;；-— ")
    return title


def _is_recent_enough(result: SearchResult, max_age_days: int = 90) -> bool:
    if not result.published_at:
        return True
    pub = _parse_datetime(result.published_at)
    if pub is None:
        return True
    now = datetime.now(timezone(timedelta(hours=8)))
    age = (now - pub).days
    return age <= max_age_days


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    # Try ISO format first
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=8)))
        except Exception:
            pass
    # Try RFC 2822 (e.g. "Fri, 03 Jul 2026 09:01:12 GMT")
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value).astimezone(timezone(timedelta(hours=8)))
    except Exception:
        pass
    return None


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
                "search_engine": result.search_engine or search_engine_name(result.source_id),
                "title": result.title,
                "url": result.url,
                "content_type": result.content_type,
                "source_weight": result.route_weight or source_weights.get(result.source_id, 0),
                "route_reason": result.route_reason,
                "metrics": result.metrics,
                "recently_recommended": bool(result.metrics.get("recently_recommended", False)),
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


def _has_chinese(value: str) -> bool:
    return any("一" <= char <= "鿿" for char in value)


def _translate_en_to_zh(text: str) -> str:
    if not text or len(text.strip()) < 10:
        return text
    if _has_chinese(text):
        return text
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q={urllib.parse.quote(text[:2000])}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data and data[0]:
            return "".join(item[0] for item in data[0] if item[0])
    except Exception:
        pass
    return text
