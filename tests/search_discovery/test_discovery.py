from src.search_discovery.discovery import cluster_results
from src.search_discovery.types import CreatorProfile, EnrichedContent, SearchResult


def test_cluster_results_groups_by_keyword_and_title_overlap():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent"],
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent GitHub",
            keyword_category="tech_project",
            title="AI Agent framework",
            url="https://github.com/example/agent",
            snippet="开源 agent framework",
            content_type="repo",
        )
    ]
    contents = [
        EnrichedContent(
            result_id="r1",
            url="https://github.com/example/agent",
            title="AI Agent framework",
            content="开源 agent framework",
            content_quality="high",
            evidence_confidence="high",
        )
    ]

    topics = cluster_results(profile, results, contents, source_weights={"github_search": 95})

    assert len(topics) == 1
    assert topics[0].matched_keywords == ["AI Agent"]
    assert topics[0].detail_level == "high"


def test_cluster_results_deduplicates_same_url_across_queries():
    profile = CreatorProfile(
        creator_id="creator_001",
        role="科技类博主",
        profile_type="tech_ai_creator",
        custom_keywords=["AI Agent", "MCP"],
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent in:name,description stars:>50",
            keyword_category="tech_project",
            title="example/agent-framework",
            url="https://github.com/example/agent-framework",
            snippet="AI Agent framework with MCP support",
            content_type="repo",
        ),
        SearchResult(
            result_id="r2",
            source_id="github_search",
            source_role="vertical_project",
            query="MCP in:name,description stars:>50",
            keyword_category="tech_tutorial",
            title="example/agent-framework",
            url="https://github.com/example/agent-framework",
            snippet="AI Agent framework with MCP support",
            content_type="repo",
        ),
    ]
    contents = [
        EnrichedContent(
            result_id="r1",
            url="https://github.com/example/agent-framework",
            title="example/agent-framework",
            content="AI Agent framework with MCP support",
            content_quality="high",
            evidence_confidence="high",
        ),
        EnrichedContent(
            result_id="r2",
            url="https://github.com/example/agent-framework",
            title="example/agent-framework",
            content="AI Agent framework with MCP support",
            content_quality="high",
            evidence_confidence="high",
        ),
    ]

    topics = cluster_results(profile, results, contents, source_weights={"github_search": 95})

    assert len(topics) == 1
    assert topics[0].keyword_categories == ["tech_project", "tech_tutorial"]
    assert topics[0].matched_keywords == ["AI Agent", "MCP"]
    assert len(topics[0].source_hits) == 1


def test_cluster_results_prefers_result_route_weight_over_profile_weight():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "custom_keywords": ["AI Agent"],
        }
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="github_search",
            source_role="vertical_project",
            query="AI Agent in:name,description stars:>50 pushed:>2025-01-01",
            keyword_category="tech_project",
            title="AI Agent Framework",
            url="https://github.com/example/agent-framework",
            snippet="AI Agent framework",
            content_type="repo",
            route_weight=100,
            route_reason="dynamic route",
        )
    ]

    topics = cluster_results(profile, results, [], source_weights={"github_search": 80})

    assert topics[0].source_hits[0]["source_weight"] == 100


def test_cluster_results_carries_github_metrics_into_source_hits():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "科技类博主",
            "profile_type": "tech_ai_creator",
            "custom_keywords": ["AI Agent"],
        }
    )
    result = SearchResult(
        result_id="r1",
        source_id="github_search",
        source_role="vertical_project",
        query="AI Agent in:name,description,readme stars:>200 pushed:>2026-01-01",
        keyword_category="tech_project",
        title="owner/agent-framework",
        url="https://github.com/owner/agent-framework",
        snippet="AI Agent framework",
        content_type="repo",
        metrics={
            "stars": 1200,
            "forks": 88,
            "language": "Python",
            "updated_at": "2026-06-21T10:00:00Z",
            "recently_recommended": True,
        },
    )

    topics = cluster_results(profile, [result], [], source_weights={"github_search": 100})

    hit = topics[0].source_hits[0]
    assert hit["search_engine"] == "GitHub Search"
    assert hit["metrics"]["stars"] == 1200
    assert hit["metrics"]["forks"] == 88
    assert hit["metrics"]["language"] == "Python"
    assert hit["recently_recommended"] is True


def test_cluster_results_adds_match_and_verification_scores():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "汽车博主",
            "profile_type": "general_hot_topic_creator",
            "track_tags": ["新能源车"],
            "custom_keywords": ["比亚迪", "价格战"],
        }
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="tianapi_news",
            source_role="news",
            query="比亚迪 价格战 最新",
            keyword_category="topic_discovery",
            title="比亚迪回应新能源车价格战",
            url="https://example.com/news-1",
            snippet="比亚迪回应价格战，新能源车市场持续受关注",
            content_type="news",
            published_at="2026-07-07T09:00:00+08:00",
        ),
        SearchResult(
            result_id="r2",
            source_id="baidu_qianfan_search",
            source_role="search",
            query="新能源车 价格战 最新",
            keyword_category="topic_discovery",
            title="比亚迪回应新能源车价格战",
            url="https://example.com/news-1",
            snippet="多家来源提到新能源车价格战",
            content_type="news",
            published_at="2026-07-07T09:30:00+08:00",
        ),
    ]
    contents = [
        EnrichedContent(
            result_id="r1",
            url="https://example.com/news-1",
            title="比亚迪回应新能源车价格战",
            content="比亚迪回应新能源车价格战，官方信息仍需核验。",
            published_at="2026-07-07T09:00:00+08:00",
            content_quality="medium_high",
            evidence_confidence="high",
        )
    ]

    topics = cluster_results(profile, results, contents, source_weights={"tianapi_news": 90, "baidu_qianfan_search": 85})

    assert topics[0].profile_match_score >= 85
    assert topics[0].verification_score >= 80
    assert topics[0].evidence_level == "strong"


def test_cluster_results_filters_generic_keywords_and_channel_titles():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_finance_001",
            "role": "财经类博主",
            "profile_type": "business_startup_creator",
            "track_tags": ["A股", "股票", "财经"],
            "custom_keywords": ["A股", "央行", "涨停", "复盘", "投资"],
        }
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="baidu_qianfan_search",
            source_role="search",
            query="A股 央行 涨停 最新",
            keyword_category="topic_discovery",
            title="财经",
            url="https://wap.eastmoney.com/channel/list.html?channel=8",
            snippet="东方财富财经频道入口",
            content_type="web",
            published_at="2026-07-07T09:00:00+08:00",
        ),
        SearchResult(
            result_id="r2",
            source_id="baidu_qianfan_search",
            source_role="search",
            query="A股 股票 最新",
            keyword_category="topic_discovery",
            title="股票",
            url="https://stock.eastmoney.com/",
            snippet="股票频道入口",
            content_type="web",
            published_at="2026-07-07T09:00:00+08:00",
        ),
        SearchResult(
            result_id="r3",
            source_id="baidu_qianfan_search",
            source_role="search",
            query="A股 涨停 最新",
            keyword_category="topic_discovery",
            title="新浪财经客户端",
            url="https://guba.sina.cn/list_192378.html",
            snippet="客户端和社区入口",
            content_type="web",
            published_at="2026-07-07T09:00:00+08:00",
        ),
        SearchResult(
            result_id="r4",
            source_id="baidu_qianfan_search",
            source_role="search",
            query="A股 交易新规 最新",
            keyword_category="topic_discovery",
            title="A股交易新规落地首日，ST板块成交放量",
            url="https://example.com/a-stock-rule",
            snippet="A股交易新规落地首日，ST板块成交明显放量，市场关注后续影响。",
            content_type="news",
            published_at="2026-07-07T09:30:00+08:00",
        ),
    ]

    topics = cluster_results(profile, results, [], source_weights={"baidu_qianfan_search": 85})

    titles = [topic.title for topic in topics]
    assert titles == ["A股交易新规落地首日，ST板块成交放量"]


def test_cluster_results_filters_english_results_for_domestic_topics():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_finance_001",
            "role": "财经类博主",
            "profile_type": "business_startup_creator",
            "track_tags": ["A股", "股票", "财经"],
            "custom_keywords": ["A股", "央行", "涨停", "复盘", "投资"],
        }
    )
    results = [
        SearchResult(
            result_id="r1",
            source_id="tavily_search",
            source_role="search",
            query="A股 央行 涨停 投资 最新",
            keyword_category="topic_discovery",
            title="Yen Hits Fresh 40-Year Low Versus Dollar; Traders Alert for Possible FX Intervention",
            url="https://www.marketscreener.com/news/yen-hits-fresh-low",
            snippet="The yen weakened again as traders watched for intervention.",
            content_type="news",
            published_at="2026-07-07T09:00:00+08:00",
        ),
        SearchResult(
            result_id="r2",
            source_id="baidu_qianfan_search",
            source_role="search",
            query="A股 交易新规 最新",
            keyword_category="topic_discovery",
            title="A股交易新规落地首日，ST板块成交放量",
            url="https://example.com/a-stock-rule",
            snippet="A股交易新规落地首日，ST板块成交明显放量。",
            content_type="news",
            published_at="2026-07-07T09:30:00+08:00",
        ),
    ]

    topics = cluster_results(profile, results, [], source_weights={"tavily_search": 70, "baidu_qianfan_search": 85})

    titles = [topic.title for topic in topics]
    assert titles == ["A股交易新规落地首日，ST板块成交放量"]


def test_cluster_results_repairs_generic_channel_title_from_specific_snippet():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_finance_001",
            "role": "财经类博主",
            "profile_type": "business_startup_creator",
            "track_tags": ["A股", "股票", "财经"],
            "custom_keywords": ["A股", "央行", "涨停", "复盘", "投资"],
        }
    )
    result = SearchResult(
        result_id="r1",
        source_id="baidu_qianfan_search",
        source_role="search",
        query="A股 央行 涨停 最新",
        keyword_category="topic_discovery",
        title="股票",
        url="https://emwap.eastmoney.com/channel/list.html?channel=9&column=407",
        snippet="证监会网站 1628读 昨天19:20 A股重大调整 就在下周一! 主板ST股涨跌幅改为10% 有何影响? 专题 证券时报 360读 昨天16:08",
        content_type="web",
        published_at="2026-07-07T09:00:00+08:00",
    )

    topics = cluster_results(profile, [result], [], source_weights={"baidu_qianfan_search": 85})

    assert len(topics) == 1
    assert topics[0].title == "A股重大调整 就在下周一! 主板ST股涨跌幅改为10% 有何影响?"
