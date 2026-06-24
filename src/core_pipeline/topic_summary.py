import json
from pathlib import Path
from typing import Any


SUMMARY_KEYS = ("mode", "what_happened", "why_it_matters", "creator_angle", "tracking_hint")


def generate_rule_summary(topic: dict[str, Any], clean_content: str) -> dict[str, str]:
    title = str(topic.get("title", "")).strip() or "该话题"
    domain_path = [str(item) for item in topic.get("domain_path", [])]
    content_modes = [str(item) for item in topic.get("content_modes", [])]
    audience_tags = [str(item) for item in topic.get("audience_tags", [])]
    domain = " > ".join(domain_path) if domain_path else "未分类"
    audience = "、".join(audience_tags) if audience_tags else "泛大众"
    modes = "、".join(content_modes) if content_modes else "话题跟进"
    first_sentence = _first_sentence(clean_content) or title
    return {
        "mode": "rule",
        "what_happened": first_sentence if title in first_sentence else f"{title}：{first_sentence}",
        "why_it_matters": f"该话题归入{domain}，主要影响或吸引{audience}。",
        "creator_angle": f"适合创作者做{modes}。",
        "tracking_hint": _tracking_hint(topic),
    }


def select_display_summary(card: dict[str, Any]) -> dict[str, str]:
    for key in ("manual_summary", "model_summary", "summary"):
        value = card.get(key)
        if isinstance(value, dict) and value.get("what_happened"):
            return _normalize_summary(value, str(value.get("mode") or key))
    clean_content = str(card.get("clean_content", "")).strip()
    return {
        "mode": "fallback",
        "what_happened": _first_sentence(clean_content) or "暂无摘要。",
        "why_it_matters": "",
        "creator_angle": "",
        "tracking_hint": "",
    }


def load_manual_summaries(path: str | Path) -> dict[str, dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    summaries: dict[str, dict[str, str]] = {}
    for title, summary in data.items():
        if isinstance(summary, dict):
            summaries[str(title)] = _normalize_summary(summary, "manual")
    return summaries


def _normalize_summary(summary: dict[str, Any], mode: str) -> dict[str, str]:
    return {
        "mode": str(summary.get("mode") or mode),
        "what_happened": str(summary.get("what_happened", "")).strip(),
        "why_it_matters": str(summary.get("why_it_matters", "")).strip(),
        "creator_angle": str(summary.get("creator_angle", "")).strip(),
        "tracking_hint": str(summary.get("tracking_hint", "")).strip(),
    }


def _first_sentence(text: str) -> str:
    compact = " ".join(str(text or "").split())
    if not compact:
        return ""
    for marker in ("。", "！", "？", ".", "!", "?"):
        if marker in compact:
            return compact.split(marker, 1)[0].strip() + marker
    return compact[:120].strip()


def _tracking_hint(topic: dict[str, Any]) -> str:
    traceability = str(topic.get("traceability", ""))
    domain_path = [str(item) for item in topic.get("domain_path", [])]
    if "高考" in domain_path:
        return "后续可追踪志愿填报时间、录取批次变化和考生反馈。"
    if traceability == "high":
        return "后续可追踪官方更新、平台讨论变化和相关事件进展。"
    if traceability == "medium":
        return "后续可观察是否出现官方补充信息或跨平台扩散。"
    return "可低频观察，若没有新信息不建议持续追。"