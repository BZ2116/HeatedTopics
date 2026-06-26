from src.search_discovery.types import CandidateTopic


def render_topics_markdown(topics: list[CandidateTopic], generated_at: str) -> str:
    lines = [
        "# 关键词搜索话题推荐",
        "",
        f"- 生成时间：{generated_at}",
        f"- 候选话题数：{len(topics)}",
        "",
    ]
    for index, topic in enumerate(topics, start=1):
        lines.extend(
            [
                f"## {index}. {topic.title}",
                "",
                f"- 分数：{topic.topic_score}",
                f"- 匹配关键词：{', '.join(topic.matched_keywords) or '无'}",
                f"- 关键词分类：{', '.join(topic.keyword_categories)}",
                f"- 新鲜度：{topic.freshness}",
                f"- 详情等级：{topic.detail_level}",
                f"- 风险等级：{topic.risk_level}",
                "",
                topic.summary,
                "",
                "### 来源",
            ]
        )
        for hit in topic.source_hits:
            title = str(hit.get("title", ""))
            url = str(hit.get("url", ""))
            source_id = str(hit.get("source_id", ""))
            lines.append(f"- `{source_id}` [{title}]({url})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"