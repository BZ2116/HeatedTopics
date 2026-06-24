from pathlib import Path
import json
import tempfile

from src.core_pipeline.topic_summary import (
    generate_rule_summary,
    load_manual_summaries,
    select_display_summary,
)


def test_generate_rule_summary_for_education_topic():
    topic = {
        "title": "河北高考分数线",
        "domain_path": ["教育升学", "高考", "分数线"],
        "content_modes": ["数据整理", "实时跟进"],
        "audience_tags": ["学生", "家长"],
        "traceability": "high",
        "risk_level": "low",
    }

    summary = generate_rule_summary(
        topic,
        "河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。",
    )

    assert summary["mode"] == "rule"
    assert "河北高考分数线" in summary["what_happened"]
    assert "学生" in summary["why_it_matters"]
    assert "数据整理" in summary["creator_angle"]
    assert "后续" in summary["tracking_hint"]


def test_select_display_summary_prefers_manual_then_model_then_rule():
    rule = {"mode": "rule", "what_happened": "rule", "why_it_matters": "", "creator_angle": "", "tracking_hint": ""}
    model = {"mode": "model", "what_happened": "model", "why_it_matters": "", "creator_angle": "", "tracking_hint": ""}
    manual = {"mode": "manual", "what_happened": "manual", "why_it_matters": "", "creator_angle": "", "tracking_hint": ""}

    assert select_display_summary({"summary": rule})["what_happened"] == "rule"
    assert select_display_summary({"summary": rule, "model_summary": model})["what_happened"] == "model"
    assert select_display_summary({"summary": rule, "model_summary": model, "manual_summary": manual})["what_happened"] == "manual"


def test_load_manual_summaries_normalizes_shape_by_title():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "topic_summaries.json"
        path.write_text(
            json.dumps(
                {
                    "河北高考分数线": {
                        "what_happened": "人工整理发生了什么",
                        "why_it_matters": "人工整理重要性",
                        "creator_angle": "人工整理创作角度",
                        "tracking_hint": "人工整理追踪点",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        summaries = load_manual_summaries(path)

    assert summaries["河北高考分数线"]["mode"] == "manual"
    assert summaries["河北高考分数线"]["what_happened"] == "人工整理发生了什么"


def test_load_manual_summaries_returns_empty_for_missing_or_invalid_file():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.json"
        invalid = Path(tmp) / "invalid.json"
        invalid.write_text("not json", encoding="utf-8")

        assert load_manual_summaries(missing) == {}
        assert load_manual_summaries(invalid) == {}