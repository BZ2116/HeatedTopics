import re
from dataclasses import asdict, dataclass
from typing import Any

from src.core_pipeline.topic_content_cleaner import clean_topic_content
from src.core_pipeline.topic_summary import generate_rule_summary


SCHEMA_VERSION = "1.0"

DOMAIN_RULES = [
    {
        "path": ["教育升学", "高考", "分数线"],
        "terms": ["高考", "分数线", "本科线", "物理组", "历史组"],
        "audience": ["学生", "家长"],
        "modes": ["数据整理", "实时跟进"],
    },
    {
        "path": ["教育升学", "高考", "志愿填报"],
        "terms": ["志愿填报", "报志愿", "专业选择", "院校选择", "填报指南"],
        "audience": ["学生", "家长"],
        "modes": ["经验攻略", "数据整理"],
    },
    {
        "path": ["财经商业", "汽车消费", "新车上市"],
        "terms": ["新车", "上市", "售价", "汽车", "车型"],
        "audience": ["年轻消费群体", "城市居民"],
        "modes": ["数据整理", "观点评论"],
    },
    {
        "path": ["科技AI", "AI应用", "医疗AI"],
        "terms": ["医疗ai", "ai医疗", "医生", "辅助诊断"],
        "audience": ["技术从业者", "泛大众"],
        "modes": ["科普解释", "观点评论"],
    },
    {
        "path": ["社会民生", "公共安全", "案件通报"],
        "terms": ["拘留", "通报", "警方", "案件", "违法"],
        "audience": ["泛大众", "城市居民"],
        "modes": ["实时跟进", "案例复盘"],
    },
]

CONTENT_MODE_ALIASES = {
    "经验攻略": ["攻略", "指南", "教程", "怎么选", "避坑"],
    "数据整理": ["汇总", "名单", "表格", "分数线", "清单"],
    "情绪共鸣": ["破防", "焦虑", "吐槽", "共鸣"],
    "政策解读": ["政策", "规定", "办法", "通知"],
    "实时跟进": ["公布", "发布", "最新", "今日", "刚刚"],
}

EVENT_PATTERNS = {
    "分数线公布": ["分数线公布", "分数线", "本科线"],
    "志愿填报": ["志愿填报", "报志愿"],
    "新车上市": ["新车上市", "上市", "售价"],
    "政策发布": ["政策发布", "规定", "通知"],
    "判决结果": ["判决", "获刑", "处罚"],
}


@dataclass(frozen=True)
class TopicHotness:
    best_rank: int | None
    platforms: list[str]
    hot_values: list[dict[str, str]]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def classify_topic(
    topic: dict[str, Any],
    hot_records: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    manual_summaries: dict[str, dict[str, str]] | None = None,
    model_summaries: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    title = str(topic.get("canonical_title") or topic.get("title") or topic.get("topic_key") or "")
    topic_key = str(topic.get("topic_key") or title)
    topic_record_ids = {str(record_id) for record_id in topic.get("hot_record_ids", []) if record_id}
    related_records = [record for record in hot_records if str(record.get("id", "")) in topic_record_ids]
    related_details = [
        row for row in detail_rows
        if str(row.get("title", "")) == title or str(row.get("title", "")) == topic_key
    ]
    text = _combined_text(title, related_records, related_details)
    domain_path, domain_terms, confidence = _select_domain_path(text, title)
    content_modes, mode_terms = _select_content_modes(text, domain_path)
    audience_tags = _select_audience_tags(text, domain_path)
    keywords = extract_keyword_fields(text)
    hotness = _topic_hotness(topic, related_records)
    traceability = _traceability(related_details, hotness.platforms)
    freshness = _freshness(text)
    risk_level = _risk_level(text, domain_path)
    creator_fit_score = _creator_fit_score(hotness, traceability, content_modes, confidence, risk_level)
    raw_detail = _detail_text(related_details)
    cleaned = clean_topic_content(title, raw_detail)
    summary_topic = {
        "title": title,
        "domain_path": domain_path,
        "content_modes": content_modes,
        "audience_tags": audience_tags,
        "traceability": traceability,
        "risk_level": risk_level,
    }
    rule_summary = generate_rule_summary(summary_topic, cleaned.clean_content)
    manual_summary = (manual_summaries or {}).get(title) or (manual_summaries or {}).get(topic_key)
    model_summary = (model_summaries or {}).get(title) or (model_summaries or {}).get(topic_key)
    platforms = hotness.platforms or list(topic.get("platforms", []))
    return {
        "topic_id": str(topic.get("topic_id") or topic_key),
        "topic_key": topic_key,
        "title": title,
        "domain_path": domain_path,
        "secondary_domain_paths": [],
        "content_modes": content_modes,
        "audience_tags": audience_tags,
        "entity_keywords": keywords["entity_keywords"],
        "event_keywords": keywords["event_keywords"],
        "match_terms": keywords["match_terms"],
        "hotness": asdict(hotness),
        "traceability": traceability,
        "freshness": freshness,
        "risk_level": risk_level,
        "creator_fit_score": creator_fit_score,
        "classification_confidence": confidence,
        "match_signals": {
            "domain_terms": domain_terms,
            "content_mode_terms": mode_terms,
            "audience_terms": [tag for tag in audience_tags if tag in text],
        },
        "card": {
            "source_platforms": platforms,
            "hotness_label": _hotness_label(hotness),
            "raw_content_preview": cleaned.raw_content_preview,
            "clean_content": cleaned.clean_content,
            "summary": rule_summary,
            "manual_summary": manual_summary,
            "model_summary": model_summary,
            "risk_note": _risk_note(risk_level, domain_path),
            "content_quality": cleaned.content_quality,
            "removed_line_count": cleaned.removed_line_count,
            "evidence_urls": _evidence_urls(related_details),
        },
    }


def _combined_text(title: str, records: list[dict[str, Any]], detail_rows: list[dict[str, Any]]) -> str:
    parts = [title]
    parts.extend(str(record.get("title", "")) for record in records)
    parts.extend(str(record.get("desc", "")) for record in records)
    parts.extend(str(row.get("content", ""))[:1000] for row in detail_rows)
    return "\n".join(part for part in parts if part)


def _select_domain_path(text: str, title: str) -> tuple[list[str], list[str], str]:
    normalized_text = normalize_text(text)
    normalized_title = normalize_text(title)
    best_rule = None
    best_score = 0
    best_title_score = 0
    best_terms: list[str] = []
    for rule in DOMAIN_RULES:
        score = 0
        title_score = 0
        terms = []
        for term in rule["terms"]:
            normalized_term = normalize_text(term)
            if normalized_term in normalized_title:
                title_score += 5
                score += 5
                terms.append(term)
            elif normalized_term in normalized_text:
                score += 2
                terms.append(term)
        if score > best_score:
            best_rule = rule
            best_score = score
            best_title_score = title_score
            best_terms = terms
    if best_rule is None or best_score < 2 or (best_title_score == 0 and best_score < 8):
        return ["未分类", "待人工确认"], [], "low"
    confidence = "high" if best_score >= 5 else "medium"
    return list(best_rule["path"]), best_terms[:5], confidence


def _select_content_modes(text: str, domain_path: list[str]) -> tuple[list[str], list[str]]:
    normalized = normalize_text(text)
    modes: list[str] = []
    terms: list[str] = []
    for rule in DOMAIN_RULES:
        if rule["path"] == domain_path:
            modes.extend(rule["modes"])
    for mode, aliases in CONTENT_MODE_ALIASES.items():
        for alias in aliases:
            if normalize_text(alias) in normalized:
                modes.append(mode)
                terms.append(alias)
                break
    return _unique_limited(modes, 5), _unique_limited(terms, 8)


def _select_audience_tags(text: str, domain_path: list[str]) -> list[str]:
    tags: list[str] = []
    for rule in DOMAIN_RULES:
        if rule["path"] == domain_path:
            tags.extend(rule["audience"])
    normalized = normalize_text(text)
    explicit = {
        "学生": ["学生", "考生"],
        "家长": ["家长", "父母"],
        "打工人": ["上班", "职场", "打工"],
        "投资者": ["投资", "股民"],
        "技术从业者": ["开发者", "程序员", "工程师"],
    }
    for tag, aliases in explicit.items():
        if any(normalize_text(alias) in normalized for alias in aliases):
            tags.append(tag)
    return _unique_limited(tags or ["泛大众"], 3)


def extract_keyword_fields(text: str) -> dict[str, list[str]]:
    chinese_candidates = re.findall(r"[一-鿿]{2,4}", text)
    alphanumeric_candidates = re.findall(r"[A-Za-z0-9]{2,12}", text)
    stop_words = {"今日", "最新", "热门", "话题", "详情", "内容"}
    entity_keywords = [
        item for item in chinese_candidates + alphanumeric_candidates
        if item not in stop_words
    ]
    event_keywords = []
    normalized = normalize_text(text)
    for event, aliases in EVENT_PATTERNS.items():
        if any(normalize_text(alias) in normalized for alias in aliases):
            event_keywords.append(event)
    match_terms = _build_match_terms(entity_keywords, event_keywords)
    return {
        "entity_keywords": _unique_limited(entity_keywords, 12),
        "event_keywords": _unique_limited(event_keywords, 8),
        "match_terms": _unique_limited(match_terms, 12),
    }


def _build_match_terms(entity_keywords: list[str], event_keywords: list[str]) -> list[str]:
    terms: list[str] = []
    for entity in entity_keywords[:6]:
        terms.append(entity)
        for event in event_keywords[:2]:
            terms.append(f"{entity}{event}")
    return terms


def _topic_hotness(topic: dict[str, Any], records: list[dict[str, Any]]) -> TopicHotness:
    platforms = _unique_limited(
        [str(record.get("platform", "")) for record in records if record.get("platform")]
        or [str(platform) for platform in topic.get("platforms", [])],
        10,
    )
    hot_values = [
        {"platform": str(record.get("platform", "")), "value": str(record.get("hot_value", ""))}
        for record in records
        if record.get("platform") and record.get("hot_value") is not None
    ]
    rank = topic.get("best_rank")
    if not isinstance(rank, int):
        ranks = [record.get("rank") for record in records if isinstance(record.get("rank"), int)]
        rank = min(ranks) if ranks else None
    return TopicHotness(best_rank=rank, platforms=platforms, hot_values=hot_values)


def _traceability(detail_rows: list[dict[str, Any]], platforms: list[str]) -> str:
    ok_details = [row for row in detail_rows if str(row.get("content", "")).strip()]
    if len(platforms) >= 2 or len(ok_details) >= 2:
        return "high"
    if ok_details or platforms:
        return "medium"
    return "low"


def _freshness(text: str) -> str:
    normalized = normalize_text(text)
    if any(term in normalized for term in ("刚刚", "今日", "今天", "公布", "发布")):
        return "breaking"
    return "ongoing"


def _risk_level(text: str, domain_path: list[str]) -> str:
    normalized = normalize_text(text)
    high_terms = ["政治", "外交", "涉密"]
    medium_terms = ["违法", "拘留", "医疗", "投资", "未成年", "争议"]
    if any(term in normalized for term in high_terms):
        return "high"
    if any(term in normalized for term in medium_terms) or "案件通报" in domain_path:
        return "medium"
    return "low"


def _creator_fit_score(
    hotness: TopicHotness,
    traceability: str,
    content_modes: list[str],
    confidence: str,
    risk_level: str,
) -> int:
    score = 40
    if hotness.best_rank is not None:
        score += max(0, 25 - min(hotness.best_rank, 25))
    score += {"high": 15, "medium": 8, "low": 0}[traceability]
    score += min(len(content_modes), 5) * 4
    score += {"high": 10, "medium": 5, "low": 0}[confidence]
    score -= {"low": 0, "medium": 8, "high": 20}[risk_level]
    return max(0, min(100, score))


def _detail_text(detail_rows: list[dict[str, Any]]) -> str:
    for row in detail_rows:
        content = str(row.get("content", "")).strip()
        if content:
            return content[:500]
    return "暂无可用详情，已根据热榜标题和元数据生成基础卡片。"


def _evidence_urls(detail_rows: list[dict[str, Any]]) -> list[str]:
    urls = [str(row.get("url", "")) for row in detail_rows if row.get("url")]
    return _unique_limited(urls, 5)


def _hotness_label(hotness: TopicHotness) -> str:
    rank = f"排名 {hotness.best_rank}" if hotness.best_rank is not None else "排名未知"
    values = [
        f"{row['platform']}热度 {row['value']}"
        for row in hotness.hot_values
        if row.get("platform") or row.get("value")
    ]
    return "；".join([rank] + values)


def _risk_note(risk_level: str, domain_path: list[str]) -> str:
    if risk_level == "high":
        return "高风险话题，发布前需核对权威来源并谨慎表达。"
    if risk_level == "medium":
        return "存在争议或专业风险，建议补充可靠来源和上下文。"
    if "教育升学" in domain_path:
        return "教育信息需核对官方来源。"
    return "常规风险，注意核对来源。"


def _unique_limited(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def build_creator_topic_index(
    topics: list[dict[str, Any]],
    hot_records: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    generated_at: str,
    source_files: list[str],
    manual_summaries: dict[str, dict[str, str]] | None = None,
    model_summaries: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    topic_records = []
    for index, topic in enumerate(topics, start=1):
        enriched_topic = dict(topic)
        enriched_topic.setdefault("topic_id", f"topic_{index:03d}")
        topic_records.append(
            classify_topic(
                enriched_topic,
                hot_records,
                detail_rows,
                manual_summaries=manual_summaries,
                model_summaries=model_summaries,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_files": source_files,
        "topics": topic_records,
    }
