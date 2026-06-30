from typing import Any


def render_topic_analysis_markdown(analysis: dict[str, Any]) -> str:
    generated_at = str(analysis.get("generated_at", ""))
    stats = analysis.get("statistics") if isinstance(analysis.get("statistics"), dict) else {}
    topics = [topic for topic in analysis.get("topics", []) if isinstance(topic, dict)]
    lines = [
        "# 选题分析报告",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## 本轮概览",
        "",
        f"- 共 {stats.get('total_topics', 0)} 个候选话题，{stats.get('total_results', 0)} 条搜索结果，{stats.get('total_evidence', 0)} 条证据。",
        f"- 近期重复推荐：{stats.get('recently_recommended_count', 0)} 个来源命中。",
        "",
    ]
    if not topics:
        lines.extend(["No usable search topics were found.", ""])
        return "\n".join(lines)

    lines.extend(_summary_section(analysis))
    lines.extend(["## Top 选题", ""])
    for index, topic in enumerate(topics[:10], start=1):
        suggestion = _topic_suggestion(analysis, topic)
        lines.extend(
            [
                f"### {index}. {topic.get('title', '')}",
                "",
                f"- 推荐级别：{topic.get('priority', '')} / {topic.get('topic_score', 0)}",
                f"- 摘要：{suggestion.get('one_line_summary', '')}",
                f"- 为什么值得做：{suggestion.get('why_it_matters', '')}",
                f"- 推荐形式：{suggestion.get('recommended_format', '')}",
                f"- 创作角度：{', '.join(_string_list(suggestion.get('creator_angles')))}",
                f"- 风险和核验：{'; '.join(_string_list(suggestion.get('verification_notes')))}",
                "- 证据来源：",
            ]
        )
        for evidence in _evidence_rows(topic):
            title = str(evidence.get("title", "untitled"))
            url = str(evidence.get("url", ""))
            if url:
                lines.append(f"  - [{title}]({url})")
            else:
                lines.append(f"  - {title}")
        lines.append("")

    lines.extend(_statistics_appendix(stats))
    return "\n".join(lines)


def _summary_section(analysis: dict[str, Any]) -> list[str]:
    synthesis = analysis.get("model_synthesis") if isinstance(analysis.get("model_synthesis"), dict) else {}
    overall = synthesis.get("overall_summary") if isinstance(synthesis.get("overall_summary"), dict) else {}
    if overall:
        return [
            "## 归纳总结",
            "",
            f"- 核心结论：{overall.get('core_conclusion', '')}",
            f"- 话题格局：{overall.get('topic_landscape', '')}",
            f"- 创作者策略：{overall.get('creator_strategy', '')}",
            f"- 风险核验：{overall.get('risk_and_verification', '')}",
            "",
        ]
    stats = analysis.get("statistics") if isinstance(analysis.get("statistics"), dict) else {}
    return [
        "## 归纳总结",
        "",
        f"- 本轮主要从 {', '.join((stats.get('source_distribution') or {}).keys()) or '已配置来源'} 收集候选话题。",
        "- 当前为规则归纳结果，适合先做选题筛选，再人工核验关键事实。",
        "",
    ]


def _topic_suggestion(analysis: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    topic_id = str(topic.get("topic_id", ""))
    synthesis = analysis.get("model_synthesis") if isinstance(analysis.get("model_synthesis"), dict) else {}
    suggestions = synthesis.get("topic_suggestions") if isinstance(synthesis.get("topic_suggestions"), dict) else {}
    model_suggestion = suggestions.get(topic_id)
    if isinstance(model_suggestion, dict) and any(str(value or "").strip() for value in model_suggestion.values() if not isinstance(value, list)):
        return model_suggestion
    rule = topic.get("rule_summary")
    return rule if isinstance(rule, dict) else {}


def _evidence_rows(topic: dict[str, Any]) -> list[dict[str, Any]]:
    rows = topic.get("evidence")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _statistics_appendix(stats: dict[str, Any]) -> list[str]:
    lines = ["## 统计附录", ""]
    for title, key in (
        ("来源分布", "source_distribution"),
        ("关键词分布", "keyword_distribution"),
        ("内容类型", "content_type_distribution"),
        ("风险分布", "risk_distribution"),
        ("时效分布", "freshness_distribution"),
        ("分数区间", "score_buckets"),
    ):
        lines.extend([f"### {title}", ""])
        values = stats.get(key) if isinstance(stats.get(key), dict) else {}
        if not values:
            lines.extend(["- 无", ""])
            continue
        for name, count in values.items():
            lines.append(f"- `{name}`: {count}")
        lines.append("")
    return lines


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]