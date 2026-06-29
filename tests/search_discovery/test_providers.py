from src.search_discovery.providers import MockProvider, SearchProviderRegistry, normalize_provider_rows


def test_normalize_provider_rows_discards_title_only_rows():
    rows = [
        {"title": "只有标题"},
        {"title": "AI Agent 新闻", "url": "https://example.com/a", "snippet": "发布新功能"},
    ]

    results = normalize_provider_rows(
        rows=rows,
        source_id="baidu_qianfan_search",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        fetched_at="2026-06-26T12:00:00+08:00",
    )

    assert len(results) == 1
    assert results[0].title == "AI Agent 新闻"


def test_normalize_provider_rows_keeps_route_metadata():
    results = normalize_provider_rows(
        rows=[
            {
                "result_id": "r1",
                "title": "example/agent-framework",
                "url": "https://github.com/example/agent-framework",
                "snippet": "Agent framework",
                "route_weight": 100,
                "route_reason": "GitHub route reason",
                "matched_keywords": ["AI Agent"],
            }
        ],
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
        keyword_category="tech_project",
        fetched_at="2026-06-29T12:00:00+08:00",
    )

    assert results[0].route_weight == 100
    assert results[0].route_reason == "GitHub route reason"
    assert results[0].matched_keywords == ["AI Agent"]


def test_registry_calls_matching_provider():
    provider = MockProvider(
        source_id="baidu_qianfan_search",
        rows=[{"title": "AI Agent 新闻", "url": "https://example.com/a", "snippet": "发布新功能"}],
    )
    registry = SearchProviderRegistry([provider])

    results = registry.search(
        source_id="baidu_qianfan_search",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        fetched_at="2026-06-26T12:00:00+08:00",
    )

    assert results[0].source_id == "baidu_qianfan_search"
    assert results[0].url == "https://example.com/a"