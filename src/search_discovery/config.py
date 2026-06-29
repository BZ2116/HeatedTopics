from src.search_discovery.types import PlannedSource, SourceConfig


def source_registry() -> dict[str, SourceConfig]:
    return {
        "baidu_qianfan_search": SourceConfig("baidu_qianfan_search", "primary_search", "medium", 90),
        "news_api_cn": SourceConfig("news_api_cn", "news_search", "medium_high", 85),
        "github_search": SourceConfig("github_search", "vertical_project", "high", 80),
        "juejin_content": SourceConfig("juejin_content", "vertical_article", "medium_high", 75, stability="experimental"),
        "tianapi_news": SourceConfig("tianapi_news", "news_search", "medium_high", 80),
        "qiniu_web_search": SourceConfig("qiniu_web_search", "serp_fallback", "medium", 70),
        "serpapi_baidu": SourceConfig("serpapi_baidu", "serp_fallback", "medium", 65),
        "dataforseo_baidu": SourceConfig("dataforseo_baidu", "serp_fallback", "medium", 60),
        "searchapi_baidu": SourceConfig("searchapi_baidu", "serp_fallback", "medium", 60),
        "dailyhot_reference": SourceConfig("dailyhot_reference", "heat_reference", "low", 25),
    }


PROFILE_SOURCE_WEIGHTS = {
    "tech_ai_creator": {
        "baidu_qianfan_search": 80,
        "news_api_cn": 60,
        "github_search": 95,
        "juejin_content": 90,
        "tianapi_news": 70,
        "qiniu_web_search": 55,
        "serpapi_baidu": 55,
        "dailyhot_reference": 20,
    },
    "developer_creator": {
        "baidu_qianfan_search": 70,
        "news_api_cn": 40,
        "github_search": 100,
        "juejin_content": 95,
        "tianapi_news": 45,
        "qiniu_web_search": 45,
        "serpapi_baidu": 50,
        "dailyhot_reference": 15,
    },
    "business_startup_creator": {
        "baidu_qianfan_search": 85,
        "news_api_cn": 90,
        "github_search": 35,
        "juejin_content": 30,
        "tianapi_news": 95,
        "qiniu_web_search": 70,
        "serpapi_baidu": 60,
        "dailyhot_reference": 20,
    },
    "general_hot_topic_creator": {
        "baidu_qianfan_search": 95,
        "news_api_cn": 90,
        "github_search": 5,
        "juejin_content": 5,
        "tianapi_news": 95,
        "qiniu_web_search": 75,
        "serpapi_baidu": 65,
        "dailyhot_reference": 35,
    },
}


def profile_source_weights(profile_type: str) -> dict[str, int]:
    return PROFILE_SOURCE_WEIGHTS.get(profile_type, PROFILE_SOURCE_WEIGHTS["general_hot_topic_creator"])


def keyword_categories() -> dict[str, dict[str, list[str]]]:
    return {
        "topic_discovery": {
            "terms": ["最新", "热点", "热议", "趋势", "爆火", "刷屏", "今日", "刚刚", "新进展"],
            "preferred_sources": ["baidu_qianfan_search", "news_api_cn"],
        },
        "news_article": {
            "terms": ["新闻", "报道", "官方回应", "通报", "发布", "调查", "进展", "事件"],
            "preferred_sources": ["news_api_cn", "baidu_qianfan_search"],
        },
        "deep_article": {
            "terms": ["分析", "解读", "复盘", "观点", "原因", "影响", "争议", "长文"],
            "preferred_sources": ["baidu_qianfan_search", "juejin_content", "news_api_cn"],
        },
        "tech_project": {
            "terms": ["GitHub", "开源", "框架", "工具", "库", "repo", "star", "release"],
            "preferred_sources": ["github_search", "juejin_content"],
        },
        "tech_tutorial": {
            "terms": ["教程", "实践", "案例", "源码", "部署", "测评", "对比", "最佳实践"],
            "preferred_sources": ["juejin_content", "github_search", "baidu_qianfan_search"],
        },
        "risk_sensitive": {
            "terms": ["医疗", "投资", "未成年", "事故", "案件", "违法", "辟谣", "监管"],
            "preferred_sources": ["news_api_cn", "baidu_qianfan_search"],
        },
    }


def plan_sources_for_category(profile_type: str, category: str, limit: int = 3) -> list[PlannedSource]:
    categories = keyword_categories()
    weights = profile_source_weights(profile_type)
    preferred = categories.get(category, categories["topic_discovery"])["preferred_sources"]
    planned = [
        PlannedSource(source_id=source_id, weight=weights.get(source_id, 0))
        for source_id in preferred
        if weights.get(source_id, 0) > 0
    ]
    return planned[:limit]