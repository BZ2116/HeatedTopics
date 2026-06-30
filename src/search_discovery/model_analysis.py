import json
from typing import Any, Callable

ModelCall = Callable[[list[dict[str, str]]], dict[str, Any]]


def build_model_topic_analysis(
    *,
    analysis: dict[str, Any],
    model_call: ModelCall,
    model: str,
    generated_at: str,
    max_topics: int = 12,
) -> dict[str, Any]:
    compact = _compact_analysis(analysis, max_topics=max_topics)
    messages = _messages(compact)
    try:
        raw = model_call(messages)
    except Exception as exc:
        return {
            "mode": "model_error",
            "generated_at": generated_at,
            "model": model,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    if not isinstance(raw, dict):
        return {
            "mode": "model_error",
            "generated_at": generated_at,
            "model": model,
            "error_type": "invalid_model_json",
            "message": "Model response must be a JSON object.",
        }
    return _normalize(raw, generated_at=generated_at, model=model)


def _compact_analysis(analysis: dict[str, Any], max_topics: int) -> dict[str, Any]:
    topics = [topic for topic in analysis.get("topics", []) if isinstance(topic, dict)]
    return {
        "statistics": analysis.get("statistics", {}),
        "topics": [_compact_topic(topic) for topic in topics[:max_topics]],
    }


def _compact_topic(topic: dict[str, Any]) -> dict[str, Any]:
    context = topic.get("llm_context") if isinstance(topic.get("llm_context"), dict) else {}
    rule_summary = topic.get("rule_summary") if isinstance(topic.get("rule_summary"), dict) else {}
    return {
        "topic_id": _text(topic.get("topic_id")),
        "title": _text(topic.get("title")),
        "priority": _text(topic.get("priority")),
        "topic_score": topic.get("topic_score", 0),
        "risk_level": _text(topic.get("risk_level")),
        "matched_keywords": _string_list(topic.get("matched_keywords"), 8),
        "rule_summary": {
            "one_line_summary": _text(rule_summary.get("one_line_summary")),
            "why_it_matters": _text(rule_summary.get("why_it_matters")),
            "creator_angles": _string_list(rule_summary.get("creator_angles"), 8),
            "verification_notes": _string_list(rule_summary.get("verification_notes"), 8),
        },
        "llm_context": {
            "compact_summary": _truncate(_text(context.get("compact_summary")), 500),
            "evidence_bullets": [_truncate(item, 260) for item in _string_list(context.get("evidence_bullets"), 5)],
            "source_titles": _string_list(context.get("source_titles"), 6),
            "risk_flags": _string_list(context.get("risk_flags"), 6),
        },
    }


def _messages(compact: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是严谨的中文选题分析助手。你只能根据输入的结构化搜索证据进行归纳，"
        "不要编造事实。只输出 JSON 对象，不要输出 Markdown。"
    )
    payload = {
        "task": "归纳本轮搜索发现的话题，并为每个 topic_id 给出面向创作者的建议。",
        "requirements": [
            "overall_summary 必须包含 core_conclusion、topic_landscape、creator_strategy、risk_and_verification。",
            "topic_suggestions 的 key 必须使用输入里的 topic_id。",
            "每个 topic suggestion 必须包含 one_line_summary、why_it_matters、creator_angles、recommended_format、verification_notes。",
            "没有证据的信息要写不确定，不能猜测事实。",
        ],
        "output_schema": {
            "overall_summary": {
                "core_conclusion": "string",
                "topic_landscape": "string",
                "creator_strategy": "string",
                "risk_and_verification": "string",
            },
            "topic_suggestions": {
                "topic_id": {
                    "one_line_summary": "string",
                    "why_it_matters": "string",
                    "creator_angles": ["string"],
                    "recommended_format": "string",
                    "verification_notes": ["string"],
                }
            },
        },
        "analysis": compact,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _normalize(raw: dict[str, Any], *, generated_at: str, model: str) -> dict[str, Any]:
    overall = raw.get("overall_summary") if isinstance(raw.get("overall_summary"), dict) else {}
    suggestions = raw.get("topic_suggestions") if isinstance(raw.get("topic_suggestions"), dict) else {}
    return {
        "mode": "model",
        "model": model,
        "generated_at": generated_at,
        "overall_summary": {
            "core_conclusion": _text(overall.get("core_conclusion")),
            "topic_landscape": _text(overall.get("topic_landscape")),
            "creator_strategy": _text(overall.get("creator_strategy")),
            "risk_and_verification": _text(overall.get("risk_and_verification")),
        },
        "topic_suggestions": {
            str(topic_id): _normalize_suggestion(value)
            for topic_id, value in suggestions.items()
            if isinstance(value, dict)
        },
    }


def _normalize_suggestion(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "one_line_summary": _text(value.get("one_line_summary")),
        "why_it_matters": _text(value.get("why_it_matters")),
        "creator_angles": _string_list(value.get("creator_angles"), 8),
        "recommended_format": _text(value.get("recommended_format")),
        "verification_notes": _string_list(value.get("verification_notes"), 8),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
