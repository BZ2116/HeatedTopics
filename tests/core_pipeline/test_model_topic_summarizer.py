from src.core_pipeline.model_topic_summarizer import (
    build_creator_topic_synthesis,
    build_model_summaries,
    compact_topic_for_model,
)


def test_compact_topic_for_model_keeps_high_signal_card_fields():
    topic = {
        "title": "河北高考分数线",
        "domain_path": ["教育升学", "高考", "分数线"],
        "content_modes": ["数据整理"],
        "audience_tags": ["学生", "家长"],
        "hotness": {"best_rank": 1, "platforms": ["weibo"]},
        "traceability": "high",
        "risk_level": "low",
        "card": {
            "clean_content": "河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。",
            "evidence_urls": ["https://example.com/a"],
            "platform_cards": [
                {
                    "platform": "weibo",
                    "clean_content": "微博侧重点是分数线发布和志愿填报讨论。",
                    "url": "https://example.com/weibo",
                }
            ],
        },
    }

    compact = compact_topic_for_model(topic)

    assert compact["title"] == "河北高考分数线"
    assert compact["domain_path"] == ["教育升学", "高考", "分数线"]
    assert compact["hotness"] == {"best_rank": 1, "platforms": ["weibo"]}
    assert "本科批历史科目组合485分" in compact["evidence_excerpt"]
    assert compact["platform_evidence"][0]["platform"] == "weibo"
    assert compact["evidence_urls"] == ["https://example.com/a"]


def test_build_creator_topic_synthesis_normalizes_model_json():
    index = {
        "topics": [
            {
                "title": "河北高考分数线",
                "domain_path": ["教育升学", "高考", "分数线"],
                "content_modes": ["数据整理"],
                "audience_tags": ["学生", "家长"],
                "hotness": {"best_rank": 1, "platforms": ["weibo"]},
                "traceability": "high",
                "risk_level": "low",
                "card": {"clean_content": "河北高考分数线公布。"},
            }
        ]
    }

    def fake_model(messages):
        assert messages[0]["role"] == "system"
        assert "JSON" in messages[1]["content"]
        return {
            "overall_summary": {
                "core_conclusion": "高考分数线话题适合做强时效数据卡。",
                "topic_landscape": "教育升学占主导。",
                "creator_strategy": "优先做分数线表格和志愿填报提醒。",
                "risk_and_verification": "核对官方教育考试院。",
            },
            "theme_clusters": [
                {
                    "theme": "高考数据",
                    "topics": ["河北高考分数线"],
                    "shared_insight": "用户需要快速查分和填报判断。",
                    "content_opportunities": ["分数线表格", "志愿时间线"],
                    "evidence_level": "high",
                }
            ],
            "topic_summaries": {
                "河北高考分数线": {
                    "what_happened": "河北公布高考分数线。",
                    "why_it_matters": "直接影响志愿填报。",
                    "creator_angle": "可做表格解读。",
                    "tracking_hint": "跟进一分一段表。",
                    "key_details": ["历史485分", "物理443分"],
                    "confidence": "high",
                }
            },
        }

    synthesis = build_creator_topic_synthesis(
        index=index,
        model_call=fake_model,
        generated_at="2026-06-25T10:00:00+08:00",
        model="gpt-test",
    )

    assert synthesis["schema_version"] == "1.0"
    assert synthesis["generated_at"] == "2026-06-25T10:00:00+08:00"
    assert synthesis["model"] == "gpt-test"
    assert synthesis["source_topic_count"] == 1
    assert synthesis["overall_summary"]["core_conclusion"] == "高考分数线话题适合做强时效数据卡。"
    assert synthesis["topic_summaries"]["河北高考分数线"]["mode"] == "model"
    assert synthesis["topic_summaries"]["河北高考分数线"]["key_details"] == ["历史485分", "物理443分"]


def test_build_model_summaries_extracts_card_compatible_fields():
    synthesis = {
        "topic_summaries": {
            "河北高考分数线": {
                "mode": "model",
                "what_happened": "河北公布高考分数线。",
                "why_it_matters": "影响志愿填报。",
                "creator_angle": "做表格。",
                "tracking_hint": "跟进一分一段表。",
                "key_details": ["历史485分"],
            }
        }
    }

    summaries = build_model_summaries(synthesis)

    assert summaries == {
        "河北高考分数线": {
            "mode": "model",
            "what_happened": "河北公布高考分数线。",
            "why_it_matters": "影响志愿填报。",
            "creator_angle": "做表格。",
            "tracking_hint": "跟进一分一段表。",
        }
    }
