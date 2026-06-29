from src.search_discovery.routing import build_search_routes, classify_search_intent, compact_query_keywords
from src.search_discovery.types import CreatorProfile
from datetime import date


def _tech_profile() -> CreatorProfile:
    return CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "track_tags": ["AI", "开发者工具", "开源项目"],
            "custom_keywords": ["AI Agent", "MCP", "RAG"],
            "content_goal": "寻找近期适合内容创作的技术趋势和项目",
        }
    )


def test_compact_query_keywords_prioritizes_custom_keywords():
    assert compact_query_keywords(_tech_profile()) == "AI Agent MCP RAG"


def test_classify_search_intent_detects_tech_project():
    assert classify_search_intent(_tech_profile()) == "tech_project"


def test_build_search_routes_returns_one_route_per_source():
    routes = build_search_routes(_tech_profile())

    source_ids = [route.source_id for route in routes]
    assert len(source_ids) == len(set(source_ids))
    assert set(source_ids[:2]) == {"github_search", "juejin_content"}
    assert all(route.query for route in routes)


def test_build_search_routes_uses_source_specific_queries():
    routes = {route.source_id: route for route in build_search_routes(_tech_profile())}

    assert routes["github_search"].query.startswith(
        "AI Agent MCP RAG in:name,description,readme stars:>200 pushed:>"
    )
    assert routes["juejin_content"].query == "AI Agent MCP RAG 教程 实践 案例 开发者"
    assert routes["baidu_qianfan_search"].query == "AI Agent MCP RAG 最新进展 行业动态 应用"
    assert routes["news_api_cn"].query == "AI Agent MCP RAG 最新 发布 融资 应用"
    assert routes["github_search"].weight > routes["news_api_cn"].weight


def test_github_route_uses_hunter_style_query(monkeypatch):
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "track_tags": ["AI", "开发者工具", "开源项目"],
            "custom_keywords": ["AI Agent", "MCP", "RAG"],
        }
    )

    routes = {route.source_id: route for route in build_search_routes(profile)}

    assert routes["github_search"].query.startswith(
        "AI Agent MCP RAG in:name,description,readme stars:>200 "
    )
    assert "pushed:>" in routes["github_search"].query


def test_business_profile_routes_news_above_github():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_002",
            "role": "商业创业博主",
            "profile_type": "business_startup_creator",
            "track_tags": ["SaaS", "融资", "AI 应用"],
            "custom_keywords": ["AI Agent 商业化"],
            "content_goal": "寻找行业新闻和商业趋势",
        }
    )

    routes = build_search_routes(profile)
    source_ids = [route.source_id for route in routes]
    assert source_ids[0] in {"tianapi_news", "news_api_cn"}
    assert source_ids.index("tianapi_news") < source_ids.index("github_search")
    assert source_ids.index("baidu_qianfan_search") < source_ids.index("github_search")
