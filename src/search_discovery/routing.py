from src.search_discovery.config import source_registry
from src.search_discovery.types import CreatorProfile, SearchRoute


PROFILE_BASE_WEIGHTS = {
    "tech_ai_creator": {
        "github_search": 95,
        "juejin_content": 90,
        "baidu_qianfan_search": 80,
        "news_api_cn": 65,
    },
    "developer_creator": {
        "github_search": 100,
        "juejin_content": 95,
        "baidu_qianfan_search": 70,
        "news_api_cn": 45,
    },
    "business_startup_creator": {
        "github_search": 35,
        "juejin_content": 35,
        "baidu_qianfan_search": 85,
        "news_api_cn": 90,
    },
    "general_hot_topic_creator": {
        "github_search": 5,
        "juejin_content": 10,
        "baidu_qianfan_search": 95,
        "news_api_cn": 90,
    },
}

INTENT_BOOSTS = {
    "tech_project": {
        "github_search": 20,
        "juejin_content": 10,
        "baidu_qianfan_search": -10,
        "news_api_cn": -20,
    },
    "tech_article": {
        "github_search": 5,
        "juejin_content": 20,
        "baidu_qianfan_search": 5,
        "news_api_cn": -10,
    },
    "news_trend": {
        "github_search": -20,
        "juejin_content": -10,
        "baidu_qianfan_search": 15,
        "news_api_cn": 20,
    },
    "product_trend": {
        "github_search": -10,
        "juejin_content": 0,
        "baidu_qianfan_search": 15,
        "news_api_cn": 10,
    },
    "content_angle": {
        "github_search": -5,
        "juejin_content": 5,
        "baidu_qianfan_search": 15,
        "news_api_cn": 10,
    },
}

SOURCE_QUERY_TEMPLATES = {
    "news_api_cn": "{keywords} 最新 发布 融资 应用",
    "baidu_qianfan_search": "{keywords} 最新进展 行业动态 应用",
    "github_search": "{keywords} in:name,description stars:>50 pushed:>2025-01-01",
    "juejin_content": "{keywords} 教程 实践 案例 开发者",
}


def build_search_routes(profile: CreatorProfile) -> list[SearchRoute]:
    intent = classify_search_intent(profile)
    keywords = compact_query_keywords(profile)
    sources = source_registry()
    base_weights = PROFILE_BASE_WEIGHTS.get(profile.profile_type, PROFILE_BASE_WEIGHTS["general_hot_topic_creator"])
    boosts = INTENT_BOOSTS.get(intent, INTENT_BOOSTS["content_angle"])

    routes: list[SearchRoute] = []
    for source_id, template in SOURCE_QUERY_TEMPLATES.items():
        weight = max(0, min(100, base_weights.get(source_id, 0) + boosts.get(source_id, 0)))
        if weight <= 0:
            continue
        source = sources[source_id]
        routes.append(
            SearchRoute(
                source_id=source_id,
                source_role=source.source_role,
                query=template.format(keywords=keywords),
                intent=intent,
                weight=weight,
                reason=_route_reason(profile, source_id, intent),
            )
        )
    return sorted(routes, key=lambda route: route.weight, reverse=True)


def classify_search_intent(profile: CreatorProfile) -> str:
    text = " ".join(
        [
            profile.role,
            profile.profile_type,
            profile.content_goal,
            *profile.track_tags,
            *profile.custom_keywords,
            *profile.content_modes,
        ]
    ).lower()
    if any(term in text for term in ["github", "开源", "repo", "框架", "sdk", "开发者工具", "mcp", "rag"]):
        return "tech_project"
    if any(term in text for term in ["教程", "实践", "案例", "源码", "部署", "架构"]):
        return "tech_article"
    if any(term in text for term in ["新闻", "最新", "发布", "融资", "政策", "行业"]):
        return "news_trend"
    if any(term in text for term in ["产品", "应用", "商业化", "saas", "工具"]):
        return "product_trend"
    return "content_angle"


def compact_query_keywords(profile: CreatorProfile, limit: int = 5) -> str:
    candidates = profile.custom_keywords or profile.track_tags
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        result.append(cleaned)
        if len(result) >= limit:
            break
    return " ".join(result)


def _route_reason(profile: CreatorProfile, source_id: str, intent: str) -> str:
    source_labels = {
        "github_search": "GitHub 适合召回开源项目、repo、框架和开发者工具。",
        "juejin_content": "技术内容源适合召回中文教程、实践案例和开发者文章。",
        "baidu_qianfan_search": "通用搜索适合召回中文网页、博客、问答和行业资料。",
        "news_api_cn": "新闻搜索适合召回时效新闻、发布信息和事实背景。",
    }
    return f"{profile.role or profile.profile_type} 的当前搜索意图是 {intent}，{source_labels[source_id]}"
