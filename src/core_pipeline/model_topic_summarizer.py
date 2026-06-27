import json
import os
import urllib.request
from typing import Any, Callable


SCHEMA_VERSION = "1.0"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

ModelCall = Callable[[list[dict[str, str]]], dict[str, Any]]


def compact_topic_for_model(topic: dict[str, Any], text_limit: int = 900) -> dict[str, Any]:
    card = topic.get("card", {}) if isinstance(topic.get("card"), dict) else {}
    platform_cards = card.get("platform_cards", [])
    return {
        "title": str(topic.get("title", "")).strip(),
        "domain_path": _string_list(topic.get("domain_path", []), 4),
        "content_modes": _string_list(topic.get("content_modes", []), 6),
        "audience_tags": _string_list(topic.get("audience_tags", []), 5),
        "hotness": {
            "best_rank": _optional_int((topic.get("hotness") or {}).get("best_rank") if isinstance(topic.get("hotness"), dict) else None),
            "platforms": _string_list((topic.get("hotness") or {}).get("platforms", []) if isinstance(topic.get("hotness"), dict) else [], 10),
        },
        "traceability": str(topic.get("traceability", "")).strip(),
        "risk_level": str(topic.get("risk_level", "")).strip(),
        "creator_fit_score": _optional_int(topic.get("creator_fit_score")),
        "evidence_excerpt": _truncate(str(card.get("clean_content", "")).strip(), text_limit),
        "platform_evidence": _compact_platform_cards(platform_cards, text_limit=360),
        "evidence_urls": _string_list(card.get("evidence_urls", []), 5),
    }


def build_creator_topic_synthesis(
    index: dict[str, Any],
    model_call: ModelCall,
    generated_at: str,
    model: str,
    max_topics: int = 40,
) -> dict[str, Any]:
    topics = [topic for topic in index.get("topics", []) if isinstance(topic, dict)]
    compact_topics = [compact_topic_for_model(topic) for topic in topics[:max_topics]]
    messages = build_synthesis_messages(compact_topics)
    raw = model_call(messages)
    return normalize_synthesis(raw, compact_topics, generated_at=generated_at, model=model)


def build_synthesis_messages(compact_topics: list[dict[str, Any]]) -> list[dict[str, str]]:
    system = (
        "你是严谨的中文热点选题研究员。你的任务是把一批创作者话题卡片"
        "总结成准确、凝练、可追踪的结构化数据。只根据输入证据判断，不要编造。"
    )
    user_payload = {
        "task": "请输出 JSON，总体归纳这些卡片论文/创作者话题，并为每个话题生成更准确的摘要。",
        "requirements": [
            "overall_summary 必须给出总体结论、话题格局、创作者策略、风险核验提示。",
            "theme_clusters 必须按主题合并相近话题，说明共性洞察和内容机会。",
            "topic_summaries 必须以话题 title 为 key，逐条给出 what_happened、why_it_matters、creator_angle、tracking_hint、key_details、confidence。",
            "没有证据的信息要写不确定，不要猜测事实。",
        ],
        "output_schema": {
            "overall_summary": {
                "core_conclusion": "string",
                "topic_landscape": "string",
                "creator_strategy": "string",
                "risk_and_verification": "string",
            },
            "theme_clusters": [
                {
                    "theme": "string",
                    "topics": ["title"],
                    "shared_insight": "string",
                    "content_opportunities": ["string"],
                    "evidence_level": "high|medium|low",
                }
            ],
            "topic_summaries": {
                "topic title": {
                    "what_happened": "string",
                    "why_it_matters": "string",
                    "creator_angle": "string",
                    "tracking_hint": "string",
                    "key_details": ["string"],
                    "confidence": "high|medium|low",
                }
            },
        },
        "topics": compact_topics,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def normalize_synthesis(
    raw: dict[str, Any],
    compact_topics: list[dict[str, Any]],
    generated_at: str,
    model: str,
) -> dict[str, Any]:
    raw_overall = raw.get("overall_summary") if isinstance(raw.get("overall_summary"), dict) else {}
    topic_titles = [str(topic.get("title", "")).strip() for topic in compact_topics if topic.get("title")]
    raw_topic_summaries = raw.get("topic_summaries") if isinstance(raw.get("topic_summaries"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "model": model,
        "source_topic_count": len(compact_topics),
        "overall_summary": {
            "core_conclusion": _text(raw_overall.get("core_conclusion")),
            "topic_landscape": _text(raw_overall.get("topic_landscape")),
            "creator_strategy": _text(raw_overall.get("creator_strategy")),
            "risk_and_verification": _text(raw_overall.get("risk_and_verification")),
        },
        "theme_clusters": _normalize_theme_clusters(raw.get("theme_clusters"), topic_titles),
        "topic_summaries": _normalize_topic_summaries(raw_topic_summaries, topic_titles),
    }


def build_model_summaries(synthesis: dict[str, Any]) -> dict[str, dict[str, str]]:
    topic_summaries = synthesis.get("topic_summaries")
    if not isinstance(topic_summaries, dict):
        return {}
    summaries: dict[str, dict[str, str]] = {}
    for title, summary in topic_summaries.items():
        if not isinstance(summary, dict):
            continue
        summaries[str(title)] = {
            "mode": "model",
            "what_happened": _text(summary.get("what_happened")),
            "why_it_matters": _text(summary.get("why_it_matters")),
            "creator_angle": _text(summary.get("creator_angle")),
            "tracking_hint": _text(summary.get("tracking_hint")),
        }
    return summaries


def call_openai_compatible_chat(
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("summary-mode=model requires OPENAI_API_KEY or an injected model_call")
    endpoint = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object")
    return parsed


def _normalize_topic_summaries(raw: dict[str, Any], topic_titles: list[str]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for title in topic_titles:
        value = raw.get(title)
        if not isinstance(value, dict):
            value = {}
        summaries[title] = {
            "mode": "model",
            "what_happened": _text(value.get("what_happened")),
            "why_it_matters": _text(value.get("why_it_matters")),
            "creator_angle": _text(value.get("creator_angle")),
            "tracking_hint": _text(value.get("tracking_hint")),
            "key_details": _string_list(value.get("key_details", []), 8),
            "confidence": _confidence(value.get("confidence")),
        }
    return summaries


def _normalize_theme_clusters(raw: Any, topic_titles: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    allowed_titles = set(topic_titles)
    clusters: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        topics = [title for title in _string_list(row.get("topics", []), 20) if title in allowed_titles]
        clusters.append(
            {
                "theme": _text(row.get("theme")),
                "topics": topics,
                "shared_insight": _text(row.get("shared_insight")),
                "content_opportunities": _string_list(row.get("content_opportunities", []), 8),
                "evidence_level": _confidence(row.get("evidence_level")),
            }
        )
    return clusters


def _compact_platform_cards(rows: Any, text_limit: int) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    compact = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        compact.append(
            {
                "platform": str(row.get("platform", "")).strip(),
                "url": str(row.get("url", "")).strip(),
                "excerpt": _truncate(str(row.get("clean_content", "")).strip(), text_limit),
            }
        )
    return compact


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"high", "medium", "low"} else "medium"
