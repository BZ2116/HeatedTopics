"""Deterministic Markdown, JSON, and minimal TXT recommendation renderers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Mapping

from .contracts import RecommendationBundle, RecommendationItem


PLATFORM_ORDER = ("sina_news", "thepaper", "netease_news", "toutiao", "juejin")
PLATFORM_LABELS = {
    "sina_news": "新浪新闻",
    "thepaper": "澎湃新闻",
    "netease_news": "网易新闻",
    "toutiao": "头条",
    "juejin": "掘金",
}


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe(item)
            for key, item in value.items()
            if not _secret_field(key)
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _secret_field(key: object) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key).strip())
    tokens = tuple(
        part
        for part in re.sub(r"[^a-z0-9]+", "_", separated.lower()).split("_")
        if part
    )
    compact = "".join(tokens)
    return (
        "cookie" in tokens
        or "cookies" in tokens
        or "authorization" in tokens
        or "secret" in tokens
        or compact.endswith("apikey")
    )


def _in_platform_order(
    items: tuple[RecommendationItem, ...],
) -> tuple[RecommendationItem, ...]:
    positions = {platform: index for index, platform in enumerate(PLATFORM_ORDER)}
    return tuple(
        item
        for _, item in sorted(
            enumerate(items),
            key=lambda pair: (positions.get(pair[1].platform, len(positions)), pair[0]),
        )
    )


def _render_section(
    title: str, items: tuple[RecommendationItem, ...], *, potential: bool = False
) -> list[str]:
    lines = [f"## {title}", ""]
    ordered = _in_platform_order(items)
    if not ordered:
        return [*lines, "无。", ""]
    for platform in PLATFORM_ORDER:
        platform_items = tuple(item for item in ordered if item.platform == platform)
        if not platform_items:
            continue
        lines.extend((f"### {PLATFORM_LABELS[platform]}", ""))
        for item in platform_items:
            lines.append(f"- **{item.title}**（热度等级 {item.heat_level}）")
            if potential:
                notice = str(item.evidence.get("notice") or "").strip()
                if notice:
                    lines.append(f"  - 说明：{notice}")
            lines.append(f"  - 采集时间：{item.collected_at}")
            lines.append(f"  - 详细内容：{item.detail}")
        lines.append("")
    return lines


def render_markdown(bundle: RecommendationBundle) -> str:
    """Render formal and potential records as unmistakably separate sections."""
    lines = [
        "# 热点推荐报告",
        "",
        f"- 用户：{bundle.user_id}",
        f"- 业务日期：{bundle.business_date}",
        f"- 生成状态：{bundle.status}",
        "",
    ]
    lines.extend(
        _render_section("正式推荐（热度等级 1-2）", bundle.recommendations)
    )
    lines.extend(
        _render_section(
            "潜在线索（热度等级 3，非正式推荐）",
            bundle.potential_topics,
            potential=True,
        )
    )
    if bundle.general_fallback:
        lines.extend(_render_section("通用热点（非个性化）", bundle.general_fallback))
    return "\n".join(lines).rstrip() + "\n"


def serialize_bundle(bundle: RecommendationBundle) -> str:
    """Serialize all structured recommendation evidence while filtering secret keys."""
    return json.dumps(_safe(asdict(bundle)), ensure_ascii=False, indent=2) + "\n"


def topic_txt_filename(item: RecommendationItem, sequence: int) -> str:
    """Return the stable non-title-based topic filename."""
    return f"{item.platform}_{sequence:03d}.txt"


def render_topic_txt(item: RecommendationItem) -> str:
    """Render exactly the six approved human-readable topic fields."""
    publication_time = item.publication_time or "平台未提供"
    return (
        f"标题：{item.title}\n"
        f"平台：{item.platform}\n"
        f"热点等级：{item.heat_level}\n"
        f"发布时间：{publication_time}\n"
        f"采集时间：{item.collected_at}\n\n"
        f"详细内容：\n{item.detail}\n"
    )
