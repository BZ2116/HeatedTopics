from html import escape

from src.hot_topic_types import SelectedTopic, TopicCard, TopicSource


def build_cards(topics: list[SelectedTopic], sources: list[TopicSource]) -> list[TopicCard]:
    source_by_title = {source.title: source for source in sources}
    cards: list[TopicCard] = []

    for topic in topics:
        source = source_by_title.get(topic.title)
        content = source.content_preview if source else ""
        confidence = "medium" if source and source.status == "ok" else "low"
        summary = f"{topic.title} 出现在 {len(topic.platforms)} 个平台，Demo 阶段已整理为重点观察话题。"
        background = content[:260].replace("\n", " ") if content else "暂无稳定详情来源。"

        cards.append(
            TopicCard(
                title=topic.title,
                platforms=topic.platforms,
                ranks=topic.ranks,
                summary=summary,
                background=background,
                why_hot=[
                    "平台排名靠前",
                    "具备较高讨论度",
                    "适合作为后续持续追踪对象",
                ],
                related_entities=[],
                sources=[source.source_url] if source and source.source_url else [],
                need_follow_up=True,
                confidence=confidence,
            )
        )

    return cards


def render_topic_cards(cards: list[TopicCard]) -> str:
    lines = ["# 热点详情卡", ""]
    for card in cards:
        lines.extend(
            [
                f"## {card.title}",
                "",
                f"**一句话概括：** {card.summary}",
                "",
                f"**来源平台：** {', '.join(card.platforms)}",
                "",
                f"**当前排名：** {card.ranks}",
                "",
                f"**事件背景：** {card.background}",
                "",
                "**为什么火：**",
            ]
        )
        for reason in card.why_hot:
            lines.append(f"- {reason}")
        lines.extend(
            [
                "",
                f"**相关主体：** {', '.join(card.related_entities) if card.related_entities else '待补充'}",
                "",
                f"**来源链接：** {', '.join(card.sources) if card.sources else '暂无稳定详情来源'}",
                "",
                f"**是否继续跟踪：** {'是' if card.need_follow_up else '否'}",
                "",
                f"**置信度：** {card.confidence}",
                "",
            ]
        )
    return "\n".join(lines)


def render_daily_digest(cards: list[TopicCard]) -> str:
    follow_up = [card for card in cards if card.need_follow_up]
    lines = [
        "# 当前国内热点话题简报",
        "",
        "## 今日概览",
        "",
        f"本次 Demo 共生成 {len(cards)} 张热点详情卡，其中 {len(follow_up)} 个话题建议继续跟踪。",
        "",
        "## 重点热点",
        "",
    ]
    for index, card in enumerate(cards, start=1):
        lines.append(f"{index}. **{card.title}**：{card.summary}")

    lines.extend(["", "## 跨平台共同热点", ""])
    for card in cards:
        if len(card.platforms) >= 2:
            lines.append(f"- {card.title}：出现在 {', '.join(card.platforms)}")

    lines.extend(["", "## 建议继续跟踪", ""])
    for card in follow_up:
        lines.append(f"- {card.title}：置信度 {card.confidence}")

    lines.extend(
        [
            "",
            "## 数据来源与置信度说明",
            "",
            "数据来源包括国内热榜聚合接口和可读取的公开网页。详情页读取失败的话题会标记为低置信度。",
            "",
        ]
    )
    return "\n".join(lines)


def render_static_html(markdown: str) -> str:
    escaped = escape(markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>当前国内热点话题简报</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f9; color: #111827; }}
    main {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 56px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 24px; line-height: 1.7; }}
  </style>
</head>
<body>
  <main>
    <pre>{escaped}</pre>
  </main>
</body>
</html>"""