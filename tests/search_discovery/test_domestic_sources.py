from src.search_discovery.domestic_sources import domestic_source_plan, domestic_query_for_source
from src.search_discovery.routing import build_search_routes
from src.search_discovery.types import CreatorProfile


def test_domestic_source_plan_prioritizes_news_sources_for_news_trend():
    planned = domestic_source_plan("news_trend")

    assert [row.source_id for row in planned] == [
        "tianapi_news",
        "news_api_cn",
        "baidu_qianfan_search",
        "tavily_search",
        "qiniu_web_search",
    ]


def test_domestic_query_for_source_uses_source_specific_language():
    keywords = "AI Agent 商业化"

    assert domestic_query_for_source("tianapi_news", keywords, "news_trend") == "AI Agent 商业化 最新 新闻 发布"
    assert domestic_query_for_source("baidu_qianfan_search", keywords, "deep_article") == (
        "AI Agent 商业化 深度分析 行业动态 背景"
    )
    assert domestic_query_for_source("qiniu_web_search", keywords, "product_trend") == (
        "AI Agent 商业化 最新进展 产品 应用"
    )
    assert domestic_query_for_source("tavily_search", keywords, "news_trend") == (
        "AI Agent 商业化 最新进展 新闻 背景"
    )


def test_business_profile_routes_domestic_sources_before_github():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_002",
            "role": "商业创业博主",
            "profile_type": "business_startup_creator",
            "track_tags": ["SaaS", "融资", "AI 应用"],
            "custom_keywords": ["AI Agent 商业化"],
            "content_goal": "寻找国内行业新闻和商业趋势",
        }
    )

    routes = build_search_routes(profile)
    source_ids = [route.source_id for route in routes]

    assert source_ids[:3] == ["tianapi_news", "news_api_cn", "baidu_qianfan_search"]
    assert source_ids.index("tavily_search") > source_ids.index("baidu_qianfan_search")
    assert source_ids.index("tavily_search") < source_ids.index("qiniu_web_search")
    assert "github_search" in source_ids
    assert source_ids.index("github_search") > source_ids.index("baidu_qianfan_search")
