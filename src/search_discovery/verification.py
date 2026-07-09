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
AUTHORITATIVE_DOMAINS = {
    "xinhuanet.com", "news.xinhuanet.com",
    "people.com.cn", "paper.people.com.cn",
    "cctv.com", "news.cctv.com",
    "gov.cn", "gov.",
    "edu.cn", "edu.",
    "thepaper.cn", "jiemian.com", "caixin.com",
    "yicai.com", "cls.cn", "eastmoney.com",
    "ifeng.com", "qq.com", "sina.com", "163.com",
    "sohu.com", "toutiao.com", "bilibili.com",
}
GENERIC_TITLES = {"新浪财经客户端", "东方财富网", "雪球", "知乎专栏", "微博", "微信公众号"}
VAGUE_TITLE_CHARS = 8


def assess_topic_verification(
    results: list[SearchResult],
    contents: list[EnrichedContent],
    *,
    text: str,
) -> VerificationAssessment:
    source_ids = {r.source_id for r in results if r.source_id}
    source_count = len(source_ids)

    has_news_media_source = any(
        r.source_id in NEWS_SOURCE_IDS or r.content_type == "news" for r in results
    )
    has_official_source = _contains_any(text, OFFICIAL_TERMS)
    has_clear_publish_time = any(
        r.published_at for r in results
    ) or any(c.published_at for c in contents)

    # 话题具体性：标题是否过短或泛词
    titles = [r.title.strip() for r in results if r.title.strip()]
    snippets = [r.snippet.strip() for r in results if r.snippet.strip()]
    primary_title = titles[0] if titles else ""
    title_len = len(primary_title)
    has_meaningful_content = any(len(s) > 50 for s in snippets) or any(len(t) > title_len for t in titles[1:])
    topic_is_specific = (
        title_len > VAGUE_TITLE_CHARS
        and primary_title not in GENERIC_TITLES
        and not _is_generic_phrase(primary_title)
    )

    # 权威域名
    domains = {r.domain for r in results if r.domain}
    has_authoritative_domain = any(d in AUTHORITATIVE_DOMAINS or any(a in d for a in AUTHORITATIVE_DOMAINS) for d in domains)

    # 多源加成
    multi_source_bonus = 10 if source_count >= 2 else 0
    extra_source_bonus = 5 if source_count >= 3 else 0

    # 风险词
    risk_flags = _risk_flags(text)

    score = 50
    if has_meaningful_content:
        score += 20
    if has_clear_publish_time:
        score += 15
    if has_authoritative_domain:
        score += 10
    if topic_is_specific:
        score += 10
    score += multi_source_bonus
    score += extra_source_bonus
    if not topic_is_specific and title_len < VAGUE_TITLE_CHARS:
        score -= 20
    if risk_flags:
        score -= 20
    score = max(0, min(100, score))

    single_source = source_count <= 1

    return VerificationAssessment(
        verification_score=score,
        evidence_level=_evidence_level(score),
        source_count=source_count,
        has_official_source=has_official_source,
        has_news_media_source=has_news_media_source,
        has_clear_publish_time=has_clear_publish_time,
        single_source=single_source,
        risk_flags=risk_flags,
        verification_notes=_verification_notes(
            source_count, has_clear_publish_time, risk_flags, topic_is_specific
        ),
    )


def _is_generic_phrase(title: str) -> bool:
    generic = {"财经", "股票", "新闻", "资讯", "日报", "动态", "快讯", "今日消息"}
    return title in generic or (len(title) <= 6 and all(c in "财经股票新闻资讯日报动态快讯" for c in title))


def _risk_flags(text: str) -> list[str]:
    flags: list[str] = []
    if _contains_any(text, RUMOR_TERMS):
        flags.append("包含传闻或夸张表达，不能直接当作事实。")
    if _contains_any(text, HIGH_RISK_TERMS):
        flags.append("包含高风险主题，发布前需要人工核验关键事实。")
    return flags


def _verification_notes(
    source_count: int,
    has_clear_publish_time: bool,
    risk_flags: list[str],
    topic_is_specific: bool,
) -> list[str]:
    notes: list[str] = []
    if source_count >= 2:
        notes.append("多个独立来源指向同一话题，基础可信度较高。")
    elif not topic_is_specific:
        notes.append("话题较为泛化，建议寻找更具体的事件或角度。")
    else:
        notes.append("单一来源支撑，发布前建议补充交叉证据。")
    if not has_clear_publish_time:
        notes.append("缺少明确发布时间，需复核时效性。")
    notes.extend(risk_flags)
    return notes


def _evidence_level(score: int) -> str:
    if score >= 85:
        return "strong"
    if score >= 65:
        return "medium"
    if score >= 45:
        return "low"
    return "weak"


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)
