from src.search_discovery.enrich import enrich_results
from src.search_discovery.types import SearchResult


def test_enrich_results_uses_snippet_as_content_when_reader_missing():
    result = SearchResult(
        result_id="r1",
        source_id="baidu_qianfan_search",
        source_role="primary_search",
        query="AI Agent 最新进展",
        keyword_category="topic_discovery",
        title="AI Agent 新闻",
        url="https://example.com/a",
        snippet="发布新功能",
        content_type="news",
    )

    enriched = enrich_results([result])

    assert enriched[0].content == "发布新功能"
    assert enriched[0].content_quality == "medium"