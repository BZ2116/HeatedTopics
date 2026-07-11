from heated_topics_v3.contracts import HeatMetrics, HotItem, TopicQuery
from heated_topics_v3.matching import match_hot_item_to_queries


def test_match_hot_item_to_queries_adds_query_ids_terms_and_score():
    item = HotItem(
        item_id="juejin_1",
        platform="juejin",
        item_type="article",
        title="AI Agent workflow with MCP",
        url="https://juejin.cn/post/1",
        rank=1,
        heat=HeatMetrics(value=500, label="500", metric_name="hot_rank"),
        summary="Build RAG tools for developers.",
        category="tech_article",
        matched_query_ids=(),
        fetched_at="2026-07-11T13:28:53+08:00",
        fetch_status="success",
        raw_payload={},
    )
    query = TopicQuery(
        query_id="tech_ai_creator_q_001_core_hot",
        profile_id="tech_ai_creator",
        query="AI Agent MCP RAG",
        intent="profile_core_hot",
        target_platforms=("juejin",),
        keywords=("AI Agent", "MCP", "RAG"),
        usage="filter_and_enrich_hot_lists",
        priority=100,
    )

    result = match_hot_item_to_queries(item, (query,))

    assert result.item.matched_query_ids == ("tech_ai_creator_q_001_core_hot",)
    assert result.match_terms == ("AI Agent", "MCP", "RAG")
    assert result.relevance_score == 100
    assert result.is_relevant is True


def test_match_hot_item_to_queries_penalizes_excluded_terms():
    item = HotItem(
        item_id="juejin_2",
        platform="juejin",
        item_type="article",
        title="AI Agent rumor roundup",
        url="https://juejin.cn/post/2",
        rank=2,
        heat=HeatMetrics(value=300, label="300", metric_name="hot_rank"),
        summary="Unverified rumor about developer tools.",
        category="tech_article",
        matched_query_ids=(),
        fetched_at="2026-07-11T13:28:53+08:00",
        fetch_status="success",
        raw_payload={},
    )
    query = TopicQuery(
        query_id="tech_ai_creator_q_001_core_hot",
        profile_id="tech_ai_creator",
        query="AI Agent",
        intent="profile_core_hot",
        target_platforms=("juejin",),
        keywords=("AI Agent",),
        usage="filter_and_enrich_hot_lists",
        priority=100,
    )

    result = match_hot_item_to_queries(
        item,
        (query,),
        excluded_keywords=("unverified rumor",),
    )

    assert result.excluded_terms == ("unverified rumor",)
    assert result.relevance_score == 0
    assert result.is_relevant is False
