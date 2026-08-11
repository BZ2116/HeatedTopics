"""Generate one user-level brief from all recommendation queries."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
MAX_ITEMS_PER_QUERY = 3

_SYSTEM_PROMPT = """你是中文内容运营专家。请根据用户画像和多个搜索查询下的推荐文章，写一段 150 至 300 字的中文内容简报。

要求：
1. 用一个整体段落概括所有查询，不要按查询分别输出摘要。
2. 说明各查询的主要话题、它们之间的联系，以及适合该用户人设的内容切入角度。
3. 只依据输入文章，禁止编造事实。
4. 直接输出最终简报，禁止思考过程、列表、标题、JSON、Markdown 围栏或引号。
"""

_USER_PROMPT_TEMPLATE = """# 用户画像
- 赛道一：{track_1}
- 赛道二：{track_2}
- 人设：{persona}

# 查询与推荐文章
{groups_block}

请将以上所有查询和文章合并总结为一个 150 至 300 字的中文内容简报。"""

_CHROME_TOKENS = (
    "打开", "登录", "注册", "首页", "更多", "查看更多",
    "下载", "立即下载", "点击查看", "扫码", "客户端",
)


def _looks_like_chrome(text: str) -> bool:
    if not text:
        return True
    if any(token in text for token in _CHROME_TOKENS):
        return True
    return text.startswith(("http://", "https://", "www."))


def _content(item: Any) -> Any:
    return getattr(item, "content", item)


def _usable_title(item: Any) -> str:
    title = (getattr(_content(item), "title", "") or "").strip()
    return "" if _looks_like_chrome(title) else title


def _format_groups(query_groups: list[tuple[str, list[Any]]]) -> str:
    blocks: list[str] = []
    for index, (query, items) in enumerate(query_groups, 1):
        lines = [f"## 查询 {index}：{query or '无明确查询'}"]
        for item_index, item in enumerate(items[:MAX_ITEMS_PER_QUERY], 1):
            content = _content(item)
            title = (getattr(content, "title", "") or "").strip()
            description = (getattr(content, "description", "") or "").strip()
            if not description:
                description = (getattr(content, "body_text", "") or "").strip()
            lines.append(
                f"{item_index}. 标题：{title}\n   摘要：{description[:200]}"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _fallback_overall(query_groups: list[tuple[str, list[Any]]]) -> str:
    parts: list[str] = []
    for query, items in query_groups:
        titles = [_usable_title(item) for item in items]
        titles = [title for title in titles if title]
        if not titles:
            continue
        label = query.strip() or "其他热点"
        parts.append(f"{label}方向关注{'、'.join(titles[:2])}")
    return "；".join(parts) + ("。" if parts else "")


def _clean_response(raw: str) -> str:
    cleaned = raw.strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1].strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    return cleaned


async def summarize_overall(
    *,
    query_groups: list[tuple[str, list[Any]]],
    user_context: dict[str, str],
    llm_service: Any,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Return one Chinese brief covering all query groups."""
    groups = [(query, items) for query, items in query_groups if items]
    if not groups:
        return ""
    prompt = _USER_PROMPT_TEMPLATE.format(
        track_1=user_context.get("track_1", "") or "（无）",
        track_2=user_context.get("track_2", "") or "（无）",
        persona=user_context.get("persona", "") or "（无）",
        groups_block=_format_groups(groups),
    )
    try:
        response = await asyncio.wait_for(
            llm_service.complete_with_core_memory(
                system_instruction=_SYSTEM_PROMPT,
                user_input=prompt,
                json_mode=False,
                temperature=0.3,
                max_tokens=512,
                caller="integration.overall_summary",
                inject_core_memory=False,
            ),
            timeout=timeout,
        )
        summary = _clean_response(response.content or "")
    except Exception as exc:
        logger.warning("overall summary LLM call failed: %s", exc)
        summary = ""
    return summary or _fallback_overall(groups)


__all__ = ["summarize_overall", "DEFAULT_TIMEOUT"]
