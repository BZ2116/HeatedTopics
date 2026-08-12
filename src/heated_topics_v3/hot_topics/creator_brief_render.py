"""JSON-compatible and Markdown rendering for creator briefs."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Sequence

from .creator_brief import CreatorBrief


def brief_to_dict(brief: CreatorBrief) -> dict:
    value = asdict(brief)
    value["evidence"] = [asdict(item) for item in brief.evidence]
    return value


def render_creator_briefs(briefs: Sequence[CreatorBrief]) -> str:
    sections: list[str] = ["# 今日热点创作参考"]
    for index, brief in enumerate(briefs, 1):
        sections.extend(
            [
                f"## {index:02d}. {brief.topic}",
                f"- 热点评分：{brief.trend_score}",
                f"- 证据状态：`{brief.evidence_status}`",
                f"- 覆盖平台：{', '.join(brief.platforms)}",
                f"- 摘要：{brief.summary}",
                "- 核心事实：",
                *(
                    [f"  - {fact}" for fact in brief.key_facts]
                    or ["  - 暂无可核验事实，仅作选题提示"]
                ),
                "- 参考来源：",
                *[f"  - [{item.source}]({item.url})" for item in brief.evidence],
            ]
        )
    return "\n".join(sections) + "\n"


def render_creator_briefs_json(briefs: Sequence[CreatorBrief]) -> str:
    return json.dumps([brief_to_dict(brief) for brief in briefs], ensure_ascii=False, indent=2)
