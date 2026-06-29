from src.search_discovery.types import CandidateTopic


def render_topics_markdown(topics: list[CandidateTopic], generated_at: str) -> str:
    lines = [
        "# Search Topic Recommendations",
        "",
        f"Generated at: `{generated_at}`",
        "",
    ]
    if not topics:
        lines.extend(["No usable search topics were found.", ""])
        return "\n".join(lines)

    for index, topic in enumerate(topics, start=1):
        confidence = _confidence(topic)
        route_reason = _first_nonempty([str(hit.get("route_reason", "")) for hit in topic.source_hits])
        lines.extend(
            [
                f"## {index}. {topic.title}",
                "",
                f"- 匹配原因：{route_reason or '该话题命中了用户关键词，并有可追溯搜索来源。'}",
                f"- 关键信息：{topic.summary}",
                "- 创作角度：",
                f"  - 围绕 `{', '.join(topic.matched_keywords) or topic.title}` 做趋势观察或项目盘点。",
                "  - 结合来源链接补充案例、时间线和使用场景。",
                "- 证据来源：",
            ]
        )
        for hit in topic.source_hits:
            title = str(hit.get("title", "untitled"))
            url = str(hit.get("url", ""))
            source_id = str(hit.get("source_id", ""))
            if url:
                lines.append(f"  - `{source_id}` [{title}]({url})")
        lines.extend(
            [
                f"- 可信度：{confidence}",
                f"- 风险提示：{_risk_note(topic.risk_level)}",
                "",
            ]
        )
    return "\n".join(lines)


def _confidence(topic: CandidateTopic) -> str:
    if topic.detail_level == "high" and topic.source_hits:
        return "高"
    if topic.source_hits:
        return "中"
    return "低"


def _risk_note(risk_level: str) -> str:
    if risk_level == "high":
        return "该话题涉及高风险内容，生成前需要人工核验事实和措辞。"
    if risk_level == "medium":
        return "建议核验来源发布时间和关键事实，避免过度推断。"
    return "低风险，但不要把单一来源扩大为行业共识。"


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        if value.strip():
            return value.strip()
    return ""
