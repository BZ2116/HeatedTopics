import json

from heated_topics_v3.contracts import RecommendationBundle, RecommendationItem
from heated_topics_v3.matching import TOUTIAO_UNVERIFIED_NOTICE
from heated_topics_v3.reporting import (
    render_markdown,
    render_topic_txt,
    serialize_bundle,
    topic_txt_filename,
)


NOW = "2026-07-13T08:05:00+08:00"


def _recommendation(
    item_id: str,
    platform: str,
    level: int,
    *,
    notice: str | None = None,
) -> RecommendationItem:
    evidence = {
        "source_kind": "official_hot_board" if level < 3 else "keyword_search",
        "rank": 2,
        "metric_name": "hot_value" if level < 3 else "search_rank",
        "heat_value": 98765 if level < 3 else None,
        "metrics": {"views": 321},
    }
    if notice:
        evidence["notice"] = notice
    return RecommendationItem(
        hot_item_id=item_id,
        platform=platform,
        title=f"{platform} topic",
        heat_level=level,
        fact_status="unverified",
        publication_time=None,
        collected_at=NOW,
        detail=f"detail for {item_id}",
        content_status="full_text",
        is_personalized=True,
        evidence=evidence,
        source_url=f"https://example.test/{item_id}",
    )


def _bundle() -> RecommendationBundle:
    return RecommendationBundle(
        status="generated",
        user_id="u1",
        business_date="2026-07-13",
        generated_at=NOW,
        recommendations=(
            _recommendation("juejin_1", "juejin", 1),
            _recommendation("toutiao_1", "toutiao", 1),
        ),
        potential_topics=(
            _recommendation(
                "toutiao_search", "toutiao", 3, notice=TOUTIAO_UNVERIFIED_NOTICE
            ),
        ),
        general_fallback=(),
        query_metadata={"toutiao_search_status": "success"},
    )


def test_markdown_separates_formal_and_potential_topics_in_fixed_platform_order():
    markdown = render_markdown(_bundle())

    formal = markdown.index("正式推荐（热度等级 1-2）")
    potential = markdown.index("潜在线索（热度等级 3，非正式推荐）")
    assert formal < potential
    assert markdown.index("### 头条", formal, potential) < markdown.index(
        "### 掘金", formal, potential
    )
    assert TOUTIAO_UNVERIFIED_NOTICE in markdown[potential:]


def test_json_retains_rich_structured_evidence_and_source_fields_without_secrets():
    unsafe = _bundle()
    unsafe = RecommendationBundle(
        **{
            **unsafe.__dict__,
            "query_metadata": {
                "toutiao_search_status": "success",
                "apiKey": "must-not-leak",
            },
        }
    )

    payload = json.loads(serialize_bundle(unsafe))
    item = payload["recommendations"][0]

    assert item["evidence"]["metric_name"] == "hot_value"
    assert item["evidence"]["metrics"] == {"views": 321}
    assert item["source_url"].startswith("https://")
    assert item["content_status"] == "full_text"
    assert "apiKey" not in payload["query_metadata"]
    assert "must-not-leak" not in json.dumps(payload)


def test_topic_txt_contains_only_the_six_approved_fields_and_uses_stable_filename():
    item = _recommendation("toutiao_1", "toutiao", 1)

    text = render_topic_txt(item)

    assert text == (
        "标题：toutiao topic\n"
        "平台：toutiao\n"
        "热点等级：1\n"
        "发布时间：平台未提供\n"
        f"采集时间：{NOW}\n\n"
        "详细内容：\n"
        "detail for toutiao_1\n"
    )
    assert topic_txt_filename(item, 2) == "toutiao_002.txt"
    for forbidden in ("source_url", "evidence", "fact_status", "hot_item_id"):
        assert forbidden not in text
