from src.core_pipeline.completeness import evaluate_required_details
from src.core_pipeline.source_registry import REQUIRED_DETAIL_PLATFORMS
from src.core_pipeline.topic_summary import select_display_summary
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
        required_status = evaluate_required_details(topic_key, evidence_for_topic)
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
                lines.append(f"- `{row.platform}` / `{row.source_method}` / {url}")
                lines.append(f"  {snippet}")
        else:
            lines.append("- 未采集到非空详情。")
        topic_has_required_platform = any(record.platform in REQUIRED_DETAIL_PLATFORMS for record in records)
        if topic_has_required_platform and required_status.missing_required_details:
            status_pairs = [
                f"weibo={required_status.weibo}",
                f"xiaohongshu={required_status.xiaohongshu}",
                f"baidu={required_status.baidu}",
            ]
            lines.extend(["", "### Required detail alerts", ""])
            lines.append(f"- Missing required sources: `{', '.join(required_status.missing_required_details)}`")
            lines.append(f"- Required source status: `{', '.join(status_pairs)}`")
        lines.extend(["", "### 平台详情状态", ""])
        if evidence_for_topic:
            for row in evidence_for_topic:
                lines.append(f"- {row.platform}：`{row.fetch_status}`")
        else:
            lines.append("- 未生成详情证据。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_creator_topic_cards(index: dict[str, object]) -> str:
    topics = [topic for topic in index.get("topics", []) if isinstance(topic, dict)]
    grouped: dict[str, list[dict[str, object]]] = {}
    for topic in topics:
        domain_path = topic.get("domain_path", [])
        domain = "未分类"
        if isinstance(domain_path, list) and domain_path:
            domain = str(domain_path[0])
        grouped.setdefault(domain, []).append(topic)

    lines = [
        "# 创作者热点卡片",
        "",
        f"- 生成时间：`{index.get('generated_at', '')}`",
        f"- 话题数量：`{len(topics)}`",
        "",
    ]
    card_index = 0
    for domain in sorted(grouped):
        lines.extend([f"## {domain}", ""])
        for topic in grouped[domain]:
            card_index += 1
            card = topic.get("card", {}) if isinstance(topic.get("card"), dict) else {}
            summary = select_display_summary(card)
            title = topic.get("title", "未命名话题")
            overview = _format_overview(card, topic)
            lines.extend(
                [
                    "---",
                    "",
                    f"### {card_index:02d}. {title}",
                    "",
                    f"**概览**：{overview}",
                    "",
                    "#### 一句话结论",
                    "",
                    str(summary.get("what_happened", "")),
                    "",
                    "#### 核心内容",
                    "",
                    _blockquote(_content_excerpt(card.get("clean_content", ""))),
                    "",
                    "#### 创作参考",
                    "",
                    _reference_table(
                        summary.get("creator_angle", ""),
                        summary.get("tracking_hint", ""),
                        card.get("risk_note", ""),
                    ),
                    "",
                ]
            )
            platform_cards = card.get("platform_cards", [])
            if isinstance(platform_cards, list) and platform_cards:
                lines.append("#### 平台数据整理")
                lines.append("")
                for platform_index, platform_card in enumerate(platform_cards, start=1):
                    if not isinstance(platform_card, dict):
                        continue
                    platform = str(platform_card.get("platform", "unknown"))
                    lines.append(f"##### 平台 {platform_index}: {platform}")
                    lines.append("")
                    meta_parts = [
                        f"质量：`{platform_card.get('content_quality', '')}`",
                        f"移除噪声：`{platform_card.get('removed_line_count', 0)}`",
                    ]
                    url = str(platform_card.get("url", "")).strip()
                    if url:
                        meta_parts.append(f"链接：{url}")
                    lines.append("- " + "；".join(meta_parts))
                    lines.append("")
                    lines.append(_blockquote(_content_excerpt(platform_card.get("clean_content", ""))))
                    lines.append("")
            evidence_urls = card.get("evidence_urls", [])
            if isinstance(evidence_urls, list) and evidence_urls:
                lines.append("#### 证据链接")
                lines.append("")
                lines.extend(f"- {url}" for url in evidence_urls)
                lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _bullet(label: str, value: str) -> str:
    return f"**{label}**：{value}"


def _format_hotness(card: dict[str, object]) -> str:
    return str(card.get("hotness_label", "")).strip()


def _format_classification(topic: dict[str, object]) -> str:
    domain_path = " > ".join(str(item) for item in topic.get("domain_path", []))
    audience = "、".join(str(item) for item in topic.get("audience_tags", []))
    if domain_path and audience:
        return f"{domain_path}；{audience}"
    return domain_path or audience


def _format_modes(topic: dict[str, object]) -> str:
    return "、".join(str(item) for item in topic.get("content_modes", []))


def _format_overview(card: dict[str, object], topic: dict[str, object]) -> str:
    parts = [
        _format_hotness(card),
        f"平台 {_format_source_platforms(card)}",
        f"分类 {' > '.join(str(item) for item in topic.get('domain_path', []))}",
        f"受众 {'、'.join(str(item) for item in topic.get('audience_tags', []))}",
        f"适合 {_format_modes(topic)}",
    ]
    return " | ".join(part for part in parts if part.strip())


def _format_source_platforms(card: dict[str, object]) -> str:
    platforms = card.get("source_platforms", [])
    if not isinstance(platforms, list):
        return ""
    return "、".join(str(platform) for platform in platforms if str(platform).strip())


def _content_excerpt(text: object, limit: int = 700) -> str:
    content = str(text or "").strip()
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "\n\n（内容较长，已截取前段。）"


def _reference_table(creator_angle: object, tracking_hint: object, risk_note: object) -> str:
    return "\n".join(
        [
            "| 创作者角度 | 后续追踪 | 风险提示 |",
            "| --- | --- | --- |",
            f"| {_table_cell(creator_angle)} | {_table_cell(tracking_hint)} | {_table_cell(risk_note)} |",
        ]
    )


def _table_cell(value: object) -> str:
    return str(value or "").replace("\n", "<br>").replace("|", "\\|").strip()


def _blockquote(text: object) -> str:
    stripped = str(text or "").rstrip()
    if not stripped:
        return ">"
    return "\n".join(f"> {line}" if line else ">" for line in stripped.splitlines())


def _format_hot_values(hot_values: list[object]) -> str:
    parts = []
    for row in hot_values:
        if not isinstance(row, dict):
            continue
        platform = str(row.get("platform", "")).strip()
        value = str(row.get("value", "")).strip()
        if platform or value:
            parts.append(f"{platform}:{value}" if platform else value)
    return ", ".join(parts)
