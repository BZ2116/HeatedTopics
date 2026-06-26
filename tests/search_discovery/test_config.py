from src.search_discovery.config import (
    keyword_categories,
    plan_sources_for_category,
    profile_source_weights,
    source_registry,
)


def test_source_registry_marks_dailyhot_as_reference_only():
    sources = source_registry()

    assert sources["dailyhot_reference"].source_role == "heat_reference"
    assert sources["dailyhot_reference"].default_weight == 25


def test_tech_ai_profile_weights_github_above_baidu():
    weights = profile_source_weights("tech_ai_creator")

    assert weights["github_search"] == 95
    assert weights["github_search"] > weights["baidu_qianfan_search"]


def test_keyword_categories_include_tech_project_sources():
    categories = keyword_categories()

    assert categories["tech_project"]["preferred_sources"] == ["github_search", "juejin_content"]


def test_plan_sources_uses_profile_and_category_preference_order():
    planned = plan_sources_for_category("tech_ai_creator", "tech_project")

    assert [source.source_id for source in planned] == ["github_search", "juejin_content"]
    assert [source.weight for source in planned] == [95, 90]