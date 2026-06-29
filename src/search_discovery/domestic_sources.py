from src.search_discovery.types import PlannedSource


DOMESTIC_SOURCE_PRIORITIES = {
    "news_trend": [
        PlannedSource("tianapi_news", 95),
        PlannedSource("news_api_cn", 90),
        PlannedSource("baidu_qianfan_search", 85),
        PlannedSource("qiniu_web_search", 70),
    ],
    "deep_article": [
        PlannedSource("baidu_qianfan_search", 90),
        PlannedSource("news_api_cn", 85),
        PlannedSource("qiniu_web_search", 70),
        PlannedSource("juejin_content", 60),
    ],
    "product_trend": [
        PlannedSource("baidu_qianfan_search", 90),
        PlannedSource("news_api_cn", 85),
        PlannedSource("tianapi_news", 80),
        PlannedSource("qiniu_web_search", 70),
    ],
}

DOMESTIC_QUERY_TEMPLATES = {
    "tianapi_news": {
        "news_trend": "{keywords} 最新 新闻 发布",
        "product_trend": "{keywords} 最新 发布 应用",
        "deep_article": "{keywords} 新闻 背景 解读",
    },
    "news_api_cn": {
        "news_trend": "{keywords} 最新进展 新闻 热点",
        "product_trend": "{keywords} 产品 商业化 应用",
        "deep_article": "{keywords} 深度解读 影响 分析",
    },
    "baidu_qianfan_search": {
        "news_trend": "{keywords} 最新进展 行业动态 应用",
        "product_trend": "{keywords} 最新进展 产品 应用",
        "deep_article": "{keywords} 深度分析 行业动态 背景",
    },
    "qiniu_web_search": {
        "news_trend": "{keywords} 最新 新闻 热点",
        "product_trend": "{keywords} 最新进展 产品 应用",
        "deep_article": "{keywords} 分析 解读 背景",
    },
}


def domestic_source_plan(intent: str) -> list[PlannedSource]:
    return DOMESTIC_SOURCE_PRIORITIES.get(intent, [])


def domestic_query_for_source(source_id: str, keywords: str, intent: str) -> str:
    source_templates = DOMESTIC_QUERY_TEMPLATES.get(source_id, {})
    template = source_templates.get(intent, source_templates.get("news_trend", "{keywords} 最新进展"))
    return template.format(keywords=keywords)
