from heated_topics_v3.contracts import UserProfile
from heated_topics_v3.profile_queries import build_qianfan_query, qianfan_query_units


def sample_profile(**changes):
    values = {
        "user_id": "user_001",
        "primary_track": "人工智能",
        "secondary_track": "AI应用与效率工具",
        "persona": "面向普通职场人的AI工具测评博主",
        "primary_keyword": "AI工具",
        "updated_at": "2026-07-13T00:00:00+08:00",
    }
    values.update(changes)
    return UserProfile(**values)


def test_qianfan_query_is_short_and_profile_derived():
    query = build_qianfan_query(sample_profile())
    assert "AI工具" in query
    assert "AI应用与效率工具" in query
    assert "最新热点" in query
    assert qianfan_query_units(query) <= 72


def test_query_units_count_ascii_once_and_chinese_twice():
    assert qianfan_query_units("AI工具") == 6


def test_qianfan_query_deduplicates_tokens_in_insertion_order():
    query = build_qianfan_query(sample_profile(secondary_track="AI工具", persona="AI工具"))
    assert query.split() == ["AI工具", "最新热点"]


def test_qianfan_query_truncates_at_character_boundaries():
    query = build_qianfan_query(
        sample_profile(primary_keyword="A" * 80, secondary_track="次赛道", persona="目标受众")
    )
    assert qianfan_query_units(query) <= 72
    assert not query.endswith(" ")
