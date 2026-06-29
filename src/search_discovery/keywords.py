from src.search_discovery.types import CreatorProfile, QueryBundle


QUERY_TEMPLATES = {
    "topic_discovery": ["{keyword} 最新进展", "{keyword} 热点", "{keyword} 今日", "{keyword} 趋势"],
    "news_article": ["{keyword} 新闻", "{keyword} 官方回应", "{keyword} 最新报道", "{keyword} 进展"],
    "deep_article": ["{keyword} 分析", "{keyword} 解读", "{keyword} 影响", "{keyword} 复盘"],
    "tech_project": [
        "{keyword} in:name,description stars:>50 pushed:>2025-01-01",
        "{keyword} in:readme stars:>100",
        "{keyword} topic:ai stars:>50",
        "{keyword} language:Python stars:>50",
    ],
    "tech_tutorial": ["{keyword} 教程", "{keyword} 实践", "{keyword} 案例", "{keyword} 源码"],
    "risk_sensitive": ["{keyword} 官方消息", "{keyword} 辟谣", "{keyword} 风险", "{keyword} 监管"],
}


def classify_keywords(profile: CreatorProfile) -> list[str]:
    text = " ".join(
        [profile.role, profile.profile_type, *profile.track_tags, *profile.custom_keywords, *profile.content_modes]
    ).lower()
    categories = ["topic_discovery"]
    if any(term.lower() in text for term in ["新闻", "报道", "通报", "官方"]):
        categories.append("news_article")
    if any(term.lower() in text for term in ["分析", "解读", "复盘", "观点"]):
        categories.append("deep_article")
    if any(term.lower() in text for term in ["ai", "github", "开源", "开发者", "工具", "agent", "mcp", "rag"]):
        categories.append("tech_project")
    if any(term.lower() in text for term in ["教程", "实践", "源码", "部署", "案例"]):
        categories.append("tech_tutorial")
    if any(term.lower() in text for term in ["医疗", "投资", "事故", "案件", "未成年", "监管"]):
        categories.append("risk_sensitive")
    return _unique(categories)


def generate_query_bundles(
    profile: CreatorProfile,
    categories: list[str] | None = None,
    max_queries_per_category: int = 6,
) -> list[QueryBundle]:
    selected_categories = categories or classify_keywords(profile)
    keywords = _query_keywords(profile)
    bundles: list[QueryBundle] = []
    for category in selected_categories:
        templates = QUERY_TEMPLATES.get(category, QUERY_TEMPLATES["topic_discovery"])
        bundles.append(
            QueryBundle(
                category=category,
                queries=_round_robin_queries(keywords, templates, max_queries_per_category),
            )
        )
    return bundles


def _query_keywords(profile: CreatorProfile) -> list[str]:
    if profile.custom_keywords:
        return _unique([*profile.custom_keywords, *profile.track_tags])
    return profile.all_keywords()


def _round_robin_queries(keywords: list[str], templates: list[str], limit: int) -> list[str]:
    queries: list[str] = []
    for template in templates:
        for keyword in keywords:
            queries.append(template.format(keyword=keyword))
            if len(queries) >= limit:
                return _unique(queries)
    return _unique(queries)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
