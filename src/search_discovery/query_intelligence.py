from dataclasses import dataclass

from src.search_discovery.types import CreatorProfile


@dataclass(frozen=True)
class UserSearchTerms:
    core_terms: list[str]
    entity_terms: list[str]
    domain_terms: list[str]
    event_terms: list[str]
    angle_terms: list[str]
    negative_terms: list[str]
    risk_terms: list[str]
    freshness_terms: list[str]


EVENT_HINTS = ["官方回应", "回应", "通报", "发布", "监管", "政策", "辟谣", "价格战", "降价", "涨停", "融资", "裁员", "事故"]
DOMAIN_HINTS = ["财经", "A股", "股票", "宏观经济", "新能源车", "汽车", "AI", "教育", "医疗", "消费", "本地"]
RISK_HINTS = ["投资", "医疗", "事故", "案件", "未成年", "监管", "违法", "辟谣"]
FRESHNESS_TERMS = ["最新", "今日", "刚刚", "热议"]


def split_user_terms(profile: CreatorProfile) -> UserSearchTerms:
    raw_terms = _unique([*profile.custom_keywords, *profile.track_tags])
    event_terms = [term for term in raw_terms if _contains_any(term, EVENT_HINTS)]
    domain_terms = [term for term in raw_terms if term in DOMAIN_HINTS or term in profile.track_tags]
    entity_terms = [
        term
        for term in raw_terms
        if term not in event_terms and term not in domain_terms and not _contains_any(term, RISK_HINTS)
    ]
    risk_terms = _unique([term for term in raw_terms if _contains_any(term, RISK_HINTS)])
    return UserSearchTerms(
        core_terms=raw_terms,
        entity_terms=entity_terms,
        domain_terms=domain_terms,
        event_terms=event_terms,
        angle_terms=_unique(profile.content_modes),
        negative_terms=_unique(profile.exclude_keywords),
        risk_terms=risk_terms,
        freshness_terms=FRESHNESS_TERMS.copy(),
    )


def build_domestic_queries(profile: CreatorProfile, limit: int = 8) -> list[str]:
    terms = split_user_terms(profile)
    subjects = terms.entity_terms or terms.domain_terms or terms.core_terms
    events = terms.event_terms or ["热点", "最新进展"]
    queries: list[str] = []
    for subject in subjects:
        for event in events:
            queries.append(f"{subject} {event} 最新")
            if len(queries) >= limit:
                return _unique(queries)
    for domain in terms.domain_terms:
        for event in events:
            queries.append(f"{domain} {event} 最新")
            if len(queries) >= limit:
                return _unique(queries)
    return _unique(queries)[:limit]


def score_text_match(terms: UserSearchTerms, *, title: str = "", snippet: str = "", content: str = "") -> int:
    score = 0
    title_text = title.lower()
    snippet_text = snippet.lower()
    content_text = content.lower()
    for term in terms.entity_terms:
        score += _weighted_presence(term, title_text, snippet_text, content_text, 35, 20, 10)
    for term in terms.event_terms:
        score += _weighted_presence(term, title_text, snippet_text, content_text, 30, 18, 8)
    for term in terms.domain_terms:
        score += _weighted_presence(term, title_text, snippet_text, content_text, 20, 12, 6)
    for term in terms.angle_terms:
        score += _weighted_presence(term, title_text, snippet_text, content_text, 10, 8, 4)
    for term in terms.negative_terms:
        if term and term.lower() in f"{title_text} {snippet_text} {content_text}":
            score -= 30
    return max(0, min(100, score))


def matched_terms(terms: UserSearchTerms, *, title: str = "", snippet: str = "", content: str = "") -> list[str]:
    text = f"{title} {snippet} {content}".lower()
    return [term for term in terms.core_terms if term.lower() in text]


def _weighted_presence(term: str, title: str, snippet: str, content: str, title_weight: int, snippet_weight: int, content_weight: int) -> int:
    lowered = term.lower()
    if lowered in title:
        return title_weight
    if lowered in snippet:
        return snippet_weight
    if lowered in content:
        return content_weight
    return 0


def _contains_any(value: str, terms: list[str]) -> bool:
    return any(term.lower() in value.lower() for term in terms)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
