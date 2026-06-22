from src.core_pipeline.types import DetailEvidence, HotRecord, TopicBrief


def render_markdown_report(briefs: list[TopicBrief], generated_at: str) -> str:
    lines = [
        "# 核心平台热点详情汇总",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 话题数量：`{len(briefs)}`",
        "",
    ]
    for brief in briefs:
        lines.extend(
            [
                f"## {brief.canonical_title}",
                "",
                f"- 完整度：`{brief.detail_completeness}`",
                f"- 可信度：`{brief.confidence}`",
                f"- 缺失核心详情源：`{', '.join(brief.missing_required_details) if brief.missing_required_details else '无'}`",
                f"- 证据 ID：`{', '.join(brief.evidence_ids)}`",
                "",
                "### 摘要",
                "",
                brief.summary,
                "",
                "### 关键事实",
                "",
            ]
        )
        if brief.key_facts:
            lines.extend(f"- {fact}" for fact in brief.key_facts)
        else:
            lines.append("- 未从详情证据中提取到关键事实。")
        lines.extend(["", "### 平台观察", ""])
        if brief.platform_observations:
            lines.extend(
                f"- `{platform}`：{observation}"
                for platform, observation in sorted(brief.platform_observations.items())
            )
        else:
            lines.append("- 暂无可用平台观察。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_recent_hot_topics_report(
    topics: list[dict[str, object]],
    evidence_rows: list[DetailEvidence],
    generated_at: str,
    window: str,
) -> str:
    evidence_by_topic: dict[str, list[DetailEvidence]] = {}
    for evidence in evidence_rows:
        evidence_by_topic.setdefault(evidence.topic_key, []).append(evidence)
    topics_with_detail = sum(
        1
        for topic in topics
        if any(
            row.fetch_status == "ok" and row.content.strip()
            for row in evidence_by_topic.get(str(topic.get("topic_key", topic.get("canonical_title", ""))), [])
        )
    )
    lines = [
        "# 近期热点详情汇总",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 采集窗口：`{window}`",
        f"- 去重后话题数量：`{len(topics)}`",
        f"- 有详情话题数量：`{topics_with_detail}`",
        f"- 缺失详情话题数量：`{len(topics) - topics_with_detail}`",
        "",
    ]
    for index, topic in enumerate(topics, start=1):
        title = str(topic.get("canonical_title", "未命名话题"))
        topic_key = str(topic.get("topic_key", title))
        records = [record for record in topic.get("records", []) if isinstance(record, HotRecord)]
        evidence_for_topic = evidence_by_topic.get(topic_key, [])
        lines.extend([f"## {index}. {title}", "", "### 热榜来源", ""])
        if records:
            for record in records:
                lines.append(f"- `{record.platform}`：排名 `{record.rank}`，热度 `{record.hot_value}`")
        else:
            lines.append("- 未记录热榜来源。")
        lines.extend(["", "### 详细信息", ""])
        ok_rows = [row for row in evidence_for_topic if row.fetch_status == "ok" and row.content.strip()]
        if ok_rows:
            for row in ok_rows:
                snippet = row.content.strip().replace("\n", " ")[:240]
                url = row.result_urls[0] if row.result_urls else row.url
                lines.append(f"- `{row.platform}` / `{row.query}` / {url}")
                lines.append(f"  {snippet}")
        else:
            lines.append("- 未采集到非空详情。")
        lines.extend(["", "### 平台详情状态", ""])
        if evidence_for_topic:
            for row in evidence_for_topic:
                lines.append(f"- {row.platform}：`{row.fetch_status}`")
        else:
            lines.append("- 未生成详情证据。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
