"""LLM-assisted confirmation of obvious title-only topic merges."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from typing import Any, Sequence

from .hot_topic_clustering import Topic


_GENERIC = {"如何", "看待", "评价", "原因", "进展", "最新", "什么", "影响", "事件", "问题"}


def _meaningful_tokens(title: str) -> set[str]:
    tokens: set[str] = set()
    for part in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", title.lower()):
        if part in _GENERIC or part.isdigit():
            continue
        tokens.add(part)
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            tokens.update(part[i : i + 2] for i in range(len(part) - 1))
    return {token for token in tokens if token not in _GENERIC and len(token) > 1}


def _valid_group(batch: Sequence[Topic], indices: list[int]) -> bool:
    selected = [batch[index - 1] for index in indices if 1 <= index <= len(batch)]
    if len(selected) < 2:
        return False
    token_sets = [_meaningful_tokens(topic.title) for topic in selected]
    platforms = {platform for topic in selected for platform in topic.platforms}
    if len(selected) == 2 and len(platforms) > 1:
        return True
    anchor = token_sets[0]
    return all(anchor & tokens for tokens in token_sets[1:])


def _parse_groups(content: str) -> list[list[int]]:
    clean = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S | re.I)
    match = re.search(r"\{.*\}", clean, flags=re.S)
    if not match:
        return []
    payload = json.loads(match.group(0))
    groups = payload.get("groups", []) if isinstance(payload, dict) else []
    return [
        [int(index) for index in group if isinstance(index, int)]
        for group in groups
        if isinstance(group, list) and len(group) >= 2
    ]


def _ask_llm(llm_service: Any, topics: Sequence[Topic]) -> list[list[int]]:
    import json as json_module

    rows = [
        {"index": index, "platform": topic.platforms, "title": topic.title}
        for index, topic in enumerate(topics, 1)
    ]
    prompt = (
        "只看标题，合并明确属于同一现实事件或新闻话题的标题。"
        "宁可少合并；共享中国、美国、回应、最新等泛词不算同一事件。"
        "只返回 JSON：{\"groups\":[[编号,...]]}，每组至少两个编号。\n"
        + json_module.dumps(rows, ensure_ascii=False)
    )

    async def call() -> str:
        response = await llm_service.complete_with_core_memory(
            system_instruction="只输出合法 JSON，不要输出解释。",
            user_input=prompt,
            json_mode=True,
            temperature=0.1,
            max_tokens=800,
            caller="recommendation",
            inject_core_memory=False,
        )
        return response.content or ""

    try:
        return _parse_groups(asyncio.run(call()))
    except Exception:
        return []


def merge_topics_with_llm(
    topics: Sequence[Topic], *, llm_service: Any, group_size: int = 8,
    max_topics: int = 50,
) -> tuple[Topic, ...]:
    """Confirm title-only merges in bounded groups; failures preserve input."""
    selected = list(topics[:max_topics])
    merged_indices: set[int] = set()
    output: list[Topic] = []
    for start in range(0, len(selected), group_size):
        batch = selected[start : start + group_size]
        groups = _ask_llm(llm_service, batch)
        group_map = {index: group for group in groups for index in group}
        used: set[int] = set()
        for group in groups:
            valid = [index - 1 for index in group if 1 <= index <= len(batch)]
            if len(valid) < 2 or any(index in used for index in valid):
                continue
            if not _valid_group(batch, group):
                continue
            base = batch[valid[0]]
            members = tuple(item for index in valid for item in batch[index].items)
            platforms = tuple(dict.fromkeys(item.platform for item in members))
            output.append(replace(base, items=members, platforms=platforms, platform_count=len(platforms)))
            used.update(valid)
        output.extend(topic for index, topic in enumerate(batch) if index not in used)
    output.extend(topics[max_topics:])
    return tuple(replace(topic, topic_id=f"topic_{index:03d}") for index, topic in enumerate(output, 1))
