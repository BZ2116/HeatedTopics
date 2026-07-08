from typing import Any


def render_topic_analysis_markdown(analysis: dict[str, Any]) -> str:
    generated_at = str(analysis.get("generated_at", ""))
    stats = analysis.get("statistics") if isinstance(analysis.get("statistics"), dict) else {}
    topics = [topic for topic in analysis.get("topics", []) if isinstance(topic, dict)]
    keywords = _keyword_names(stats)
    lines = [
        "# 国内热点匹配报告",
        "",
        f"生成时间：`{generated_at}`",
        f"用户关键词：`{_join_or_default(keywords, '未提供')}`",
        "搜索范围：国内新闻 / 搜索 / 官方回应 / 社区讨论",
        "",
        "## 一、本轮结论",
        "",
    ]
    if not topics:
        lines.extend(
            [
                "本轮没有发现可用的国内热点候选话题。",
                "",
                "## 二、优先推荐选题",
                "",
                "暂无可推荐选题。",
                "",
                "## 三、话题详情",
                "",
                "暂无话题详情。",
                "",
                "## 四、需要谨慎处理的话题",
                "",
                "暂无需要谨慎处理的话题。",
                "",
            ]
        )
        lines.extend(_statistics_section(stats))
        lines.extend(_keyword_section(stats))
        return "\n".join(lines)

    lines.extend(_summary_lines(analysis, topics, stats))
    lines.extend(_recommendation_table(topics))
    lines.extend(_topic_details(analysis, topics))
    lines.extend(_caution_section(topics))
    lines.extend(_statistics_section(stats))
    lines.extend(_keyword_section(stats))
    return "\n".join(lines)


def _summary_lines(analysis: dict[str, Any], topics: list[dict[str, Any]], stats: dict[str, Any]) -> list[str]:
    synthesis = analysis.get("model_synthesis") if isinstance(analysis.get("model_synthesis"), dict) else {}
    overall = synthesis.get("overall_summary") if isinstance(synthesis.get("overall_summary"), dict) else {}
    stats_line = _stats_summary_line(stats, len(topics))
    if overall and any(str(value or "").strip() for value in overall.values()):
        return [
            stats_line,
            "",
            str(overall.get("core_conclusion", "")).strip(),
            "",
            f"- 话题格局：{overall.get('topic_landscape', '')}",
            f"- 创作者策略：{overall.get('creator_strategy', '')}",
            f"- 风险核验：{overall.get('risk_and_verification', '')}",
            "",
        ]

    high_count = sum(1 for topic in topics if topic.get("priority") == "high")
    cautious_count = len(_cautious_topics(topics))
    source_count = len(stats.get("source_distribution", {}) if isinstance(stats.get("source_distribution"), dict) else {})
    top_title = str(topics[0].get("title", "优先话题")).strip()
    return [
        stats_line,
        f"本轮共发现 {len(topics)} 个候选话题，覆盖 {source_count} 类来源，其中 {high_count} 个可优先评估。",
        f"当前最值得先看的话题是“{top_title}”。仍有 {cautious_count} 个话题需要补充来源、发布时间或官方确认。",
        "",
    ]


def _stats_summary_line(stats: dict[str, Any], topic_count: int) -> str:
    total_results = stats.get("total_results", 0)
    total_evidence = stats.get("total_evidence", 0)
    return f"搜索结果总数：{total_results} 条；进入候选话题：{topic_count} 个；证据条目：{total_evidence} 条。"


def _recommendation_table(topics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## 二、优先推荐选题",
        "",
        "| 优先级 | 话题 | 匹配度 | 可信度 | 时效性 | 风险 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for topic in topics[:10]:
        verification = _verification(topic)
        lines.append(
            "| {priority} | {title} | {match_score} | {confidence} | {freshness} | {risk} |".format(
                priority=_priority_label(str(topic.get("priority", ""))),
                title=_escape_table(str(topic.get("title", ""))),
                match_score=topic.get("topic_score", 0),
                confidence=_escape_table(str(verification.get("confidence_label", "未知"))),
                freshness=_freshness_label(str(topic.get("freshness", ""))),
                risk=_escape_table(str(verification.get("risk_label", _risk_label(str(topic.get("risk_level", "")))))),
            )
        )
    lines.append("")
    return lines


def _topic_details(analysis: dict[str, Any], topics: list[dict[str, Any]]) -> list[str]:
    lines = ["## 三、话题详情", ""]
    for index, topic in enumerate(topics[:10], start=1):
        suggestion = _topic_suggestion(analysis, topic)
        verification = _verification(topic)
        angles = _string_list(suggestion.get("creator_angles"))
        titles = _string_list(topic.get("suggested_titles"))
        lines.extend(
            [
                f"### {index}. {topic.get('title', '')}",
                "",
                f"**推荐等级**：{_priority_label(str(topic.get('priority', '')))}",
                f"**话题评分**：{topic.get('topic_score', 0)}",
                f"**关键词匹配**：{_join_or_default(_string_list(topic.get('matched_keywords')), '未明确')}",
                f"**适合内容方向**：{_join_or_default(angles, '趋势观察 / 证据汇总')}",
                "",
                "**话题摘要**",
                str(suggestion.get("one_line_summary", "")).strip(),
                "",
                "**为什么值得做**",
                str(suggestion.get("why_it_matters", "")).strip(),
                "",
                "**可用创作角度**",
                "",
            ]
        )
        for angle in angles or ["趋势观察", "证据汇总", "谨慎核验"]:
            lines.append(f"- {angle}")
        lines.extend(["", "**证据来源**", "", "| 来源类型 | 来源 | 标题 | 时间 | 可信度 |", "| --- | --- | --- | --- | --- |"])
        for evidence in _evidence_rows(topic):
            title = str(evidence.get("title", "untitled"))
            url = str(evidence.get("url", ""))
            title_cell = f"[{title}]({url})" if url else title
            lines.append(
                "| {source_type} | {source_name} | {title} | {published_at} | {confidence} |".format(
                    source_type=_escape_table(str(evidence.get("source_type", "未知来源"))),
                    source_name=_escape_table(str(evidence.get("source_name", "未知来源"))),
                    title=_escape_table(title_cell),
                    published_at=_escape_table(str(evidence.get("published_at", "") or "未明确")),
                    confidence=_confidence_text(str(evidence.get("evidence_confidence", ""))),
                )
            )
        lines.extend(["", "**真实性与核验**", ""])
        notes = _merge_unique(_string_list(verification.get("notes")), _string_list(suggestion.get("verification_notes")))
        for note in notes:
            lines.append(f"- {note}")
        lines.extend(["", "**建议标题**", ""])
        for title in titles:
            lines.append(f"- {title}")
        lines.append("")
    return lines


def _caution_section(topics: list[dict[str, Any]]) -> list[str]:
    lines = ["## 四、需要谨慎处理的话题", ""]
    cautious = _cautious_topics(topics)
    if not cautious:
        return [*lines, "暂无明显高风险或证据不足的话题。", ""]
    for topic in cautious:
        verification = _verification(topic)
        notes = _string_list(verification.get("notes"))
        lines.extend(
            [
                f"### {topic.get('title', '')}",
                "",
                f"**风险等级**：{verification.get('risk_label', _risk_label(str(topic.get('risk_level', ''))))}",
                f"**原因**：{'; '.join(notes) or '证据仍需补充。'}",
                "**处理建议**：只作为观察线索，发布前补充官方来源、权威媒体报道或明确发布时间。",
                "",
            ]
        )
    return lines


def _statistics_section(stats: dict[str, Any]) -> list[str]:
    source_distribution = stats.get("source_distribution") if isinstance(stats.get("source_distribution"), dict) else {}
    risk_distribution = stats.get("risk_distribution") if isinstance(stats.get("risk_distribution"), dict) else {}
    rows = [
        ("搜索结果总数", stats.get("total_results", 0)),
        ("可用候选话题", stats.get("total_topics", 0)),
        ("高可信话题", (stats.get("score_buckets") or {}).get("80_plus", 0) if isinstance(stats.get("score_buckets"), dict) else 0),
        ("来源类型数", len(source_distribution)),
        ("缺少发布时间的话题", "见话题详情"),
        ("高风险话题", risk_distribution.get("high", 0)),
    ]
    lines = ["## 五、证据与来源统计", "", "| 指标 | 数量 |", "| --- | ---: |"]
    for name, value in rows:
        lines.append(f"| {name} | {value} |")
    lines.append("")
    return lines


def _keyword_section(stats: dict[str, Any]) -> list[str]:
    keyword_distribution = stats.get("keyword_distribution") if isinstance(stats.get("keyword_distribution"), dict) else {}
    lines = ["## 六、关键词命中情况", "", "| 关键词 | 命中话题数 | 主要方向 |", "| --- | ---: | --- |"]
    if not keyword_distribution:
        lines.append("| 未提供 | 0 | 未明确 |")
        lines.append("")
        return lines
    for keyword, count in keyword_distribution.items():
        lines.append(f"| {_escape_table(str(keyword))} | {count} | 国内热点匹配、证据汇总 |")
    lines.append("")
    return lines


def _topic_suggestion(analysis: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    topic_id = str(topic.get("topic_id", ""))
    synthesis = analysis.get("model_synthesis") if isinstance(analysis.get("model_synthesis"), dict) else {}
    suggestions = synthesis.get("topic_suggestions") if isinstance(synthesis.get("topic_suggestions"), dict) else {}
    model_suggestion = suggestions.get(topic_id)
    if isinstance(model_suggestion, dict) and any(str(value or "").strip() for value in model_suggestion.values() if not isinstance(value, list)):
        return model_suggestion
    rule = topic.get("rule_summary")
    return rule if isinstance(rule, dict) else {}


def _cautious_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for topic in topics:
        verification = _verification(topic)
        if topic.get("risk_level") in {"medium", "high"}:
            result.append(topic)
            continue
        if int(verification.get("source_count", 0) or 0) <= 1:
            result.append(topic)
            continue
        if verification.get("has_clear_publish_time") is False:
            result.append(topic)
    return result


def _verification(topic: dict[str, Any]) -> dict[str, Any]:
    value = topic.get("verification_summary")
    return value if isinstance(value, dict) else {}


def _evidence_rows(topic: dict[str, Any]) -> list[dict[str, Any]]:
    rows = topic.get("evidence")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _keyword_names(stats: dict[str, Any]) -> list[str]:
    values = stats.get("keyword_distribution") if isinstance(stats.get("keyword_distribution"), dict) else {}
    return [str(key) for key in values.keys() if str(key).strip()]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_unique(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
    return result


def _join_or_default(values: list[str], default: str) -> str:
    return "、".join(values) if values else default


def _priority_label(priority: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(priority, priority or "未知")


def _risk_label(risk: str) -> str:
    return {"low": "低", "medium": "中", "high": "高"}.get(risk, risk or "未知")


def _freshness_label(freshness: str) -> str:
    return {"breaking": "今日/近24小时", "ongoing": "持续发酵", "evergreen": "长期话题", "fading": "热度回落"}.get(freshness, freshness or "未知")


def _confidence_text(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value or "未知")


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
