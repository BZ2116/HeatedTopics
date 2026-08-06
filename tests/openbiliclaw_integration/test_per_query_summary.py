"""Tests for the overall multi-query content summary."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.openbiliclaw_integration import per_query_summary


def _make_rec(title: str = "t", description: str = "d") -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id=title,
        content_url=f"https://x.com/{title}",
        source_platform="weibo",
        body_text="b",
        description=description,
        content_type="note",
    )
    return Recommendation(
        content=item, expression="", topic_label="",
        confidence=0.8, presented=False,
    )


def _fake_llm(response: str = "整体内容围绕美食与求职展开") -> Any:
    llm = MagicMock()
    resp = MagicMock()
    resp.content = response
    llm.complete_with_core_memory = AsyncMock(return_value=resp)
    return llm


@pytest.mark.asyncio
async def test_summarize_overall_returns_empty_for_empty_groups() -> None:
    llm = _fake_llm()
    out = await per_query_summary.summarize_overall(
        query_groups=[], user_context={}, llm_service=llm,
    )
    assert out == ""
    llm.complete_with_core_memory.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_overall_calls_llm_once_for_all_queries() -> None:
    llm = _fake_llm("整体涵盖夏日美食探店和应届生面试准备两个方向")
    groups = [
        ("夏日美食", [_make_rec("重庆火锅探店", "辣味十足")]),
        ("应届生求职", [_make_rec("面试技巧", "准备方法")]),
    ]
    out = await per_query_summary.summarize_overall(
        query_groups=groups,
        user_context={"track_1": "美食", "track_2": "求职", "persona": "博主"},
        llm_service=llm,
    )
    assert out == "整体涵盖夏日美食探店和应届生面试准备两个方向"
    assert llm.complete_with_core_memory.call_count == 1
    prompt = llm.complete_with_core_memory.call_args.kwargs["user_input"]
    assert "夏日美食" in prompt
    assert "应届生求职" in prompt
    assert "重庆火锅探店" in prompt
    assert "面试技巧" in prompt


@pytest.mark.asyncio
async def test_summarize_overall_strips_fence_and_chain_of_thought() -> None:
    llm = _fake_llm("分析过程\n</think>```\n整体总结\n```")
    out = await per_query_summary.summarize_overall(
        query_groups=[("q", [_make_rec("文章", "摘要")])],
        user_context={}, llm_service=llm,
    )
    assert out == "整体总结"
    assert "分析过程" not in out
    assert "```" not in out


@pytest.mark.asyncio
async def test_summarize_overall_falls_back_on_llm_failure() -> None:
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock(side_effect=RuntimeError("boom"))
    out = await per_query_summary.summarize_overall(
        query_groups=[
            ("美食", [_make_rec("重庆火锅探店", "辣味十足")]),
            ("求职", [_make_rec("应届生面试技巧", "准备方法")]),
        ],
        user_context={}, llm_service=llm,
    )
    assert "美食" in out
    assert "重庆火锅探店" in out
    assert "求职" in out
    assert "应届生面试技巧" in out


@pytest.mark.asyncio
async def test_summarize_overall_falls_back_when_llm_returns_empty() -> None:
    llm = _fake_llm("")
    out = await per_query_summary.summarize_overall(
        query_groups=[("美食", [_make_rec("重庆夏日美食探店", "")])],
        user_context={}, llm_service=llm,
    )
    assert out
    assert "重庆夏日美食探店" in out
