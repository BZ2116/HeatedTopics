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
    assert "普通职场人" in query
    assert "最新热点" in query
    assert qianfan_query_units(query) <= 72


def test_query_units_count_ascii_once_and_non_ascii_conservatively_twice():
    assert qianfan_query_units("AI工具") == 6
    assert qianfan_query_units("é🙂") == 4


def test_qianfan_query_deduplicates_tokens_in_insertion_order():
    query = build_qianfan_query(sample_profile(secondary_track="AI工具", persona="AI工具"))
    assert query.split() == ["AI工具", "最新热点"]


def test_qianfan_query_preserves_all_components_when_inputs_are_oversized():
    query = build_qianfan_query(
        sample_profile(
            primary_keyword="P" * 80,
            secondary_track="S" * 80,
            persona="T" * 80,
        )
    )
    primary, secondary, persona, suffix = query.split()
    assert primary and set(primary) == {"P"}
    assert secondary and set(secondary) == {"S"}
    assert persona and set(persona) == {"T"}
    assert suffix == "最新热点"
    assert qianfan_query_units(query) <= 72
    assert not query.endswith(" ")
