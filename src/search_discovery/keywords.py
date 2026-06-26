from src.search_discovery.types import CreatorProfile, QueryBundle


QUERY_TEMPLATES = {
    "topic_discovery": ["{keyword} 最新进展", "{keyword} 热点", "{keyword} 今日", "{keyword} 趋势"],
    "news_article": ["{keyword} 新闻", "{keyword} 官方回应", "{keyword} 最新报道", "{keyword} 进展"],
    "deep_article": ["{keyword} 分析", "{keyword} 解读", "{keyword} 影响", "{keyword} 复盘"],
    "tech_project": ["{keyword} GitHub", "{keyword} open source", "{keyword} repo", "{keyword} release"],
    "tech_tutorial": ["{keyword} 教程", "{keyword} 实践", "{keyword} 案例", "{keyword} 源码"],
    "risk_sensitive": ["{keyword} 官方消息", "{keyword} 辟谣", "{keyword} 风险", "{keyword} 监管"],
}


def classify_keywords(profile: CreatorProfile) -> list[str]:
    text = " ".join([profile.role, profile.profile_type, *profile.track_tags, *profile.custom_keywords, *profile.content_modes]).lower()
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
    keywords = profile.all_keywords() or profile.custom_keywords or profile.track_tags
    bundles: list[QueryBundle] = []
    for category in selected_categories:
        templates = QUERY_TEMPLATES.get(category, QUERY_TEMPLATES["topic_discovery"])
        queries = []
        for keyword in keywords:
            for template in templates:
                queries.append(template.format(keyword=keyword))
        bundles.append(QueryBundle(category=category, queries=_unique(queries)[:max_queries_per_category]))
    return bundles


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