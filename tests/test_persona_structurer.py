"""Tests for persona_structurer.

The LLM-path tests use a fake `llm` callable and assert prompt shape +
parse success. The heuristic tests verify the deterministic fallback
against representative inputs from the original xlsx.
"""
from __future__ import annotations

import json

import pytest

from heated_topics_v3.persona_structurer import (
    PersonaStructureError,
    _clean_chunk,
    _split_heuristic,
    extract_short_keywords,
    structure_persona,
)


def _ok_payload(**overrides):
    base = {
        "role": "经管学生视角的AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习", "办公", "内容生产"],
        "value": "真实使用建议",
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


def test_structure_persona_calls_llm_and_returns_dataclass():
    calls = []

    def fake_llm(prompt, *, system=None, **_):
        calls.append((prompt, system))
        return _ok_payload()

    result = structure_persona(
        "科技AI",
        "AI工具应用",
        "经管学生，专做AI工具测评，给真实使用建议。",
        llm=fake_llm,
    )

    assert len(calls) == 1
    prompt, system = calls[0]
    assert system is not None and "persona" in system
    assert "科技AI" in prompt
    assert "AI工具应用" in prompt
    assert "经管学生" in prompt
    assert result.role == "经管学生视角的AI工具体验官"
    assert result.subject == "AI工具"
    assert tuple(result.scenarios) == ("写作", "学习", "办公", "内容生产")
    assert result.value == "真实使用建议"


def test_structure_persona_strips_code_fence_in_response():
    def fake_llm(_prompt, **_):
        return "```json\n" + _ok_payload() + "\n```"

    result = structure_persona(
        "科技AI", "AI工具应用", "x", llm=fake_llm,
    )
    assert result.subject == "AI工具"


def test_structure_persona_raises_on_non_json():
    def fake_llm(_prompt, **_):
        return "not json at all"

    with pytest.raises(PersonaStructureError, match="not valid JSON"):
        structure_persona("科技AI", "AI工具应用", "x", llm=fake_llm)


def test_structure_persona_raises_on_missing_field():
    def fake_llm(_prompt, **_):
        return json.dumps({"role": "x", "subject": "y", "value": "z"})

    with pytest.raises(PersonaStructureError, match="missing fields"):
        structure_persona(
            "科技AI", "AI工具应用", "x", llm=fake_llm,
        )


def test_structure_persona_raises_on_empty_scenarios():
    def fake_llm(_prompt, **_):
        return json.dumps({
            "role": "x", "subject": "y", "scenarios": [], "value": "z",
        })

    with pytest.raises(PersonaStructureError, match="scenarios"):
        structure_persona(
            "科技AI", "AI工具应用", "x", llm=fake_llm,
        )


def test_structure_persona_truncates_scenarios_to_six():
    def fake_llm(_prompt, **_):
        return json.dumps({
            "role": "x",
            "subject": "y",
            "scenarios": ["a", "b", "c", "d", "e", "f", "g", "h"],
            "value": "z",
        })

    result = structure_persona(
        "科技AI", "AI工具应用", "x", llm=fake_llm,
    )
    assert len(result.scenarios) == 6
    assert tuple(result.scenarios) == ("a", "b", "c", "d", "e", "f")


# --- heuristic tests ---

def test_heuristic_classic_three_chunk_persona():
    """yingjie_001-style: three comma-separated chunks in one sentence."""
    role, subject, scenarios, value = _split_heuristic(
        "经济学背景的实习打工人，专注拆解简历、面试和校招选择，用普通学生能听懂的话讲清职场入门。"
    )
    assert role == "经济学背景的实习打工人"
    assert value == "用普通学生能听懂的话讲清职场入门"
    assert scenarios == ["简历", "面试", "校招选择"]


def test_heuristic_handles_bu_prefix():
    """liangxing_001-style: '不煽动对立' is an anti-claim, must leave scenarios."""
    role, subject, scenarios, value = _split_heuristic(
        "关注亲密关系、婚恋观和性别沟通，不煽动对立，专门拆解男女相处中的误解、权力感和情绪博弈，适合引发讨论。"
    )
    assert scenarios
    assert "不煽动对立" not in scenarios
    assert "不煽动对立" in value


def test_heuristic_handles_ba_structure():
    """hongguan_001-style: '把 X 讲成 Y' should yield scenarios from X,
    and Y should land in value rather than the subject."""
    role, subject, scenarios, value = _split_heuristic(
        "经济学学生视角，专门把政策、利率、就业和房价讲成普通人能听懂的话，不预测暴富，只解释变化。"
    )
    assert role == "经济学学生视角"
    # X noun list survives in subject and scenarios.
    assert "政策" in subject and "房价" in subject
    assert scenarios == ["政策", "利率", "就业", "房价"]
    # Y + later anti-claims merge into value.
    assert "普通人能听懂的话" in value
    assert "不预测暴富" in value
    assert "只解释变化" in value


def test_heuristic_handles_multisentence_bio():
    """gushi_001-style: first sentence is bio, then action+value."""
    role, subject, scenarios, value = _split_heuristic(
        "人大计算机本科，北大光华金融硕士。深耕tmt行业多年，对人形机器人产业具有独到见解。"
    )
    assert "人大计算机本科" in role
    assert "北大光华金融硕士" in role
    assert subject == "深耕tmt行业多年"
    assert "人形机器人" in value


def test_heuristic_handles_two_sentence_with_bu_in_value():
    """xuesheng_001-style: '主打把复杂任务拆成可执行清单' is value."""
    role, subject, scenarios, value = _split_heuristic(
        "双专业本科生，分享备考、论文、汇报和科研入门经验，主打把复杂任务拆成可执行清单。"
    )
    assert role == "双专业本科生"
    assert value == "主打把复杂任务拆成可执行清单"
    assert scenarios[:3] == ["备考", "论文", "汇报"]
    assert len(scenarios) >= 3


def test_clean_chunk_does_not_overconsume_after_negation():
    """`不讲暴富故事` greedy {1,3} used to swallow '不讲暴富', leaving '故事'.

    Regression: the bug was that `不[一-鿿]{1,3}` matched up to 3 trailing CJK
    chars, so the negation prefix consumed more than the verb it was meant to.
    The single-char form should leave the noun phrase intact.
    """
    assert _clean_chunk("不讲暴富故事") == "暴富故事"
    assert _clean_chunk("不只看比分") == "看比分"


def test_extract_short_keywords_drops_negated_chunks():
    """licai_001-style: chunks starting with '不' must not surface as keywords.

    The whole '不X' phrase is a negation — keeping 'X' (or '故事') as a search
    term inverts the persona's intent.
    """
    kw = extract_short_keywords(
        "财经商业",
        "普通人理财",
        "不讲暴富故事，只用生活化案例拆解基金、存款、消费和资产配置，适合理财小白慢慢入门。",
    )
    assert "故事" not in kw
    assert "暴富故事" not in kw


def test_extract_short_keywords_drops_negated_subject_phrase():
    """yiren_001-style: '不追求精致' must not yield '求精致' or '精致'."""
    kw = extract_short_keywords(
        "美食生活",
        "一人食日常",
        "独居厨房实验员，记录低预算、低失败率的一人食做法，不追求精致，只追求好吃、省事、有烟火气。",
    )
    assert "求精致" not in kw
    assert "精致" not in kw


def test_extract_short_keywords_keeps_positive_subjects():
    """Negative chunks must not crowd out legitimate positive subjects from the
    same persona (licai_001 should still surface 存款/消费)."""
    kw = extract_short_keywords(
        "财经商业",
        "普通人理财",
        "不讲暴富故事，只用生活化案例拆解基金、存款、消费和资产配置，适合理财小白慢慢入门。",
    )
    assert "存款" in kw
    assert "消费" in kw
