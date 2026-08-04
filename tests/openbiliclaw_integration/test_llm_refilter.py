"""Tests for the LLM-driven secondary candidate filter (v2.1.4)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from heated_topics_v3.openbiliclaw_integration import llm_refilter


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_candidate(title: str, description: str = "") -> MagicMock:
    c = MagicMock()
    c.title = title
    c.description = description
    return c


def test_parse_judgments_bare_json() -> None:
    """LLM returns a bare JSON array → parsed as expected."""
    out = llm_refilter._parse_judgments("[true, false, true]", 3)
    assert out == [True, False, True]


def test_parse_judgments_fenced_json() -> None:
    """```json ... ``` block is unwrapped."""
    out = llm_refilter._parse_judgments("```json\n[true, false]\n```", 2)
    assert out == [True, False]


def test_parse_judgments_with_prose_prefix() -> None:
    """LLM rambles before the array → we extract the [...] slice."""
    out = llm_refilter._parse_judgments(
        "Here are my judgments: [true, false, true] hope that helps",
        3,
    )
    assert out == [True, False, True]


def test_parse_judgments_chinese_truthy_falsy() -> None:
    """Chinese yes/no tokens are accepted."""
    out = llm_refilter._parse_judgments('["符合", "不符合", "是"]', 3)
    assert out == [True, False, True]


def test_parse_judgments_wrong_length_returns_none() -> None:
    """Length mismatch → None so we keep the batch as-is."""
    assert llm_refilter._parse_judgments("[true, false]", 3) is None
    assert llm_refilter._parse_judgments("[true, false, true, true]", 3) is None


def test_parse_judgments_empty_returns_none() -> None:
    assert llm_refilter._parse_judgments("", 3) is None
    assert llm_refilter._parse_judgments("   ", 3) is None
    assert llm_refilter._parse_judgments("no json here", 3) is None


def test_parse_judgments_unknown_token_returns_none() -> None:
    """Bogus strings don't get coerced; returns None."""
    assert llm_refilter._parse_judgments('["maybe", "yes"]', 2) is None


def test_format_candidates_includes_title_and_summary() -> None:
    cands = [
        _make_candidate("非遗手工艺", "传统工艺介绍"),
        _make_candidate("Flutter UI", "widget layouts"),
    ]
    out = llm_refilter._format_candidates(cands)
    assert "1. 标题：非遗手工艺" in out
    assert "2. 标题：Flutter UI" in out
    assert "传统工艺介绍" in out
    assert "widget layouts" in out


def test_format_candidates_truncates_long_summary() -> None:
    """Summaries are capped at 300 chars to keep prompts small."""
    cands = [_make_candidate("t", description="a" * 1000)]
    out = llm_refilter._format_candidates(cands)
    assert "a" * 300 in out
    assert "a" * 301 not in out


@pytest.mark.asyncio
async def test_refilter_candidates_drops_false_judgments() -> None:
    """Batch where LLM says [true, false, true] keeps the 1st & 3rd."""
    cands = [
        _make_candidate("keep-1"),
        _make_candidate("drop-me"),
        _make_candidate("keep-2"),
    ]
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock(
        return_value=MagicMock(content="[true, false, true]"),
    )
    kept = await llm_refilter.refilter_candidates(
        cands,
        user_context={"track_1": "非遗", "track_2": "", "persona": "创作者"},
        llm_service=llm,
        batch_size=10,
    )
    assert [c.title for c in kept] == ["keep-1", "keep-2"]
    assert llm.complete_with_core_memory.call_count == 1


@pytest.mark.asyncio
async def test_refilter_candidates_keeps_all_when_unparseable() -> None:
    """Unparseable response → batch kept as-is, not silently stripped."""
    cands = [_make_candidate("a"), _make_candidate("b")]
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock(
        return_value=MagicMock(content="not json"),
    )
    kept = await llm_refilter.refilter_candidates(
        cands,
        user_context={"track_1": "", "track_2": "", "persona": ""},
        llm_service=llm,
    )
    assert [c.title for c in kept] == ["a", "b"]


@pytest.mark.asyncio
async def test_refilter_candidates_keeps_all_on_exception() -> None:
    """LLM crash → batch kept as-is, pipeline keeps going."""
    cands = [_make_candidate("a"), _make_candidate("b")]
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock(
        side_effect=RuntimeError("api down"),
    )
    kept = await llm_refilter.refilter_candidates(
        cands,
        user_context={"track_1": "", "track_2": "", "persona": ""},
        llm_service=llm,
    )
    assert [c.title for c in kept] == ["a", "b"]


@pytest.mark.asyncio
async def test_refilter_candidates_batches_large_lists() -> None:
    """15 candidates with batch_size=10 → 2 LLM calls."""
    cands = [_make_candidate(f"c-{i}") for i in range(15)]
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock(
        side_effect=[
            MagicMock(content="[" + ",".join(["true"] * 10) + "]"),
            MagicMock(content="[" + ",".join(["true"] * 5) + "]"),
        ],
    )
    kept = await llm_refilter.refilter_candidates(
        cands,
        user_context={"track_1": "x", "track_2": "", "persona": ""},
        llm_service=llm,
        batch_size=10,
    )
    assert len(kept) == 15
    assert llm.complete_with_core_memory.call_count == 2
    # First call should see candidates 1..10, second should see 11..15.
    first_prompt = llm.complete_with_core_memory.call_args_list[0].kwargs["user_input"]
    second_prompt = llm.complete_with_core_memory.call_args_list[1].kwargs["user_input"]
    assert "c-9" in first_prompt
    assert "c-10" not in first_prompt
    assert "c-10" in second_prompt


@pytest.mark.asyncio
async def test_refilter_candidates_empty_returns_empty() -> None:
    """No candidates → no LLM call."""
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock()
    kept = await llm_refilter.refilter_candidates(
        [],
        user_context={"track_1": "", "track_2": "", "persona": ""},
        llm_service=llm,
    )
    assert kept == []
    llm.complete_with_core_memory.assert_not_called()


@pytest.mark.asyncio
async def test_refilter_candidates_uses_correct_caller_id() -> None:
    """The LLM call is tagged so traces can attribute the cost."""
    llm = MagicMock()
    llm.complete_with_core_memory = AsyncMock(
        return_value=MagicMock(content="[true]"),
    )
    await llm_refilter.refilter_candidates(
        [_make_candidate("a")],
        user_context={"track_1": "", "track_2": "", "persona": ""},
        llm_service=llm,
    )
    kwargs = llm.complete_with_core_memory.call_args.kwargs
    assert kwargs["caller"] == "integration.llm_refilter"
    assert kwargs["inject_core_memory"] is False
    assert kwargs["json_mode"] is True