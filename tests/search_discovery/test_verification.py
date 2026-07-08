from src.search_discovery.types import EnrichedContent, SearchResult
from src.search_discovery.verification import assess_topic_verification


def _result(result_id, source_id, title, *, published_at="", content_type="news"):
    return SearchResult(
        result_id=result_id,
        source_id=source_id,
        source_role="primary_search",
        query="比亚迪 价格战 最新",
        keyword_category="topic_discovery",
        title=title,
        url=f"https://example.com/{result_id}",
        snippet=f"{title} 摘要",
        content_type=content_type,
        published_at=published_at,
    )


def test_assess_topic_verification_rewards_independent_sources_and_publish_time():
    results = [
        _result("r1", "tianapi_news", "比亚迪回应价格战", published_at="2026-07-07T09:00:00+08:00"),
        _result("r2", "baidu_qianfan_search", "新能源车价格战最新进展", published_at="2026-07-07T09:30:00+08:00"),
    ]
    contents = [
        EnrichedContent(result_id="r1", url="https://example.com/r1", title="比亚迪回应价格战", content="新闻证据", published_at="2026-07-07T09:00:00+08:00", evidence_confidence="high"),
        EnrichedContent(result_id="r2", url="https://example.com/r2", title="新能源车价格战最新进展", content="搜索证据", published_at="2026-07-07T09:30:00+08:00", evidence_confidence="medium"),
    ]

    assessment = assess_topic_verification(results, contents, text="比亚迪回应新能源车价格战")

    assert assessment.verification_score >= 80
    assert assessment.evidence_level == "strong"
    assert assessment.source_count == 2
    assert assessment.has_news_media_source is True
    assert assessment.has_clear_publish_time is True
    assert assessment.single_source is False


def test_assess_topic_verification_penalizes_single_source_rumor():
    results = [
        _result("r1", "baidu_qianfan_search", "网传某品牌价格战内幕", content_type="search_snippet"),
    ]

    assessment = assess_topic_verification(results, [], text="网传 小道消息 内幕 投资")

    assert assessment.verification_score < 50
    assert assessment.evidence_level == "weak"
    assert assessment.single_source is True
    assert any("单一来源" in note for note in assessment.verification_notes)
    assert any("传闻" in flag for flag in assessment.risk_flags)
