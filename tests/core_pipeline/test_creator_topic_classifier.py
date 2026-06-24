from src.core_pipeline.creator_topic_classifier import (
    classify_topic,
    extract_keyword_fields,
    normalize_text,
)


def test_classify_gaokao_score_line_uses_deep_domain_path():
    topic = {
        "topic_id": "topic_001",
        "topic_key": "河北高考分数线",
        "canonical_title": "河北高考分数线",
        "platforms": ["weibo"],
        "best_rank": 1,
    }

    result = classify_topic(topic, [], [])

    assert result["domain_path"] == ["教育升学", "高考", "分数线"]
    assert "数据整理" in result["content_modes"]
    assert "学生" in result["audience_tags"]
    assert "家长" in result["audience_tags"]
    assert result["classification_confidence"] == "high"


def test_classify_zhiyuan_guide_keeps_domain_and_mode_separate():
    topic = {
        "topic_id": "topic_002",
        "topic_key": "高考志愿填报指南",
        "canonical_title": "高考志愿填报指南",
        "platforms": ["baidu"],
        "best_rank": 3,
    }

    result = classify_topic(topic, [], [])

    assert result["domain_path"] == ["教育升学", "高考", "志愿填报"]
    assert "经验攻略" in result["content_modes"]
    assert "志愿填报" in result["event_keywords"]


def test_extract_keywords_are_bounded_and_do_not_replace_controlled_tags():
    text = "河北2026高考分数线公布，本科线、物理组443分，志愿填报即将开始。"

    keywords = extract_keyword_fields(text)

    assert len(keywords["entity_keywords"]) <= 12
    assert len(keywords["event_keywords"]) <= 8
    assert len(keywords["match_terms"]) <= 12
    assert "河北" in keywords["entity_keywords"]
    assert "分数线公布" in keywords["event_keywords"]


def test_normalize_text_lowercases_and_removes_extra_whitespace():
    assert normalize_text("  AI   医疗\n应用 ") == "ai医疗应用"
