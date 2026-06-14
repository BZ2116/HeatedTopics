from src.core_pipeline.types import TopicBrief


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