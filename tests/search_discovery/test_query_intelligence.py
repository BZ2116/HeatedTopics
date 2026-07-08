from src.search_discovery.query_intelligence import build_domestic_queries, score_text_match, split_user_terms
from src.search_discovery.types import CreatorProfile


def test_split_user_terms_identifies_domestic_entities_events_and_negative_terms():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "财经汽车类博主",
            "profile_type": "general_hot_topic_creator",
            "track_tags": ["新能源车", "汽车"],
            "custom_keywords": ["比亚迪", "价格战", "官方回应"],
            "content_modes": ["新闻解读", "影响分析"],
            "exclude_keywords": ["小道消息", "内幕"],
        }
    )

    terms = split_user_terms(profile)

    assert terms.core_terms == ["比亚迪", "价格战", "官方回应", "新能源车", "汽车"]
    assert terms.entity_terms == ["比亚迪"]
    assert terms.domain_terms == ["新能源车", "汽车"]
    assert terms.event_terms == ["价格战", "官方回应"]
    assert terms.angle_terms == ["新闻解读", "影响分析"]
    assert terms.negative_terms == ["小道消息", "内幕"]
    assert "最新" in terms.freshness_terms


def test_build_domestic_queries_combines_entities_events_and_freshness():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "汽车博主",
            "profile_type": "general_hot_topic_creator",
            "track_tags": ["新能源车"],
            "custom_keywords": ["比亚迪", "价格战", "官方回应"],
        }
    )

    queries = build_domestic_queries(profile, limit=5)

    assert queries[:3] == [
        "比亚迪 价格战 最新",
        "比亚迪 官方回应 最新",
        "新能源车 价格战 最新",
    ]
    assert len(queries) == len(set(queries))


def test_score_text_match_weights_title_entity_and_event_terms():
    profile = CreatorProfile.from_dict(
        {
            "creator_id": "creator_001",
            "role": "汽车博主",
            "profile_type": "general_hot_topic_creator",
            "track_tags": ["新能源车"],
            "custom_keywords": ["比亚迪", "价格战"],
            "exclude_keywords": ["小道消息"],
        }
    )
    terms = split_user_terms(profile)

    score = score_text_match(
        terms,
        title="比亚迪回应新能源车价格战",
        snippet="多家媒体报道车企降价影响",
        content="官方渠道称具体车型信息仍需核实。",
    )
    weak_score = score_text_match(
        terms,
        title="汽车行业观察",
        snippet="小道消息称某品牌可能有变化",
        content="暂无明确来源。",
    )

    assert score >= 85
    assert weak_score < score
