"""Tests for LLM-driven keyword extraction + per-user cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from heated_topics_v3.openbiliclaw_integration import keyword_extractor
from heated_topics_v3.openbiliclaw_integration.keyword_extractor import _fallback_keywords
from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def _spec(
    user_id: str = "u1",
    track_1: str = "非遗",
    track_2: str = "民俗",
    persona: str = "研究地方习俗",
) -> UserSpec:
    return UserSpec(
        user_id=user_id, track_1=track_1, track_2=track_2, persona=persona,
    )


def test_spec_hash_stable_for_same_input() -> None:
    h1 = keyword_extractor._spec_hash(_spec())
    h2 = keyword_extractor._spec_hash(_spec())
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_spec_hash_changes_when_track_1_changes() -> None:
    h1 = keyword_extractor._spec_hash(_spec(track_1="非遗"))
    h2 = keyword_extractor._spec_hash(_spec(track_1="手工艺"))
    assert h1 != h2


def test_spec_hash_changes_when_persona_changes() -> None:
    h1 = keyword_extractor._spec_hash(_spec(persona="研究地方习俗"))
    h2 = keyword_extractor._spec_hash(_spec(persona="关注乡村振兴"))
    assert h1 != h2


@pytest.mark.asyncio
async def test_extract_via_llm_returns_3_keywords() -> None:
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["非遗手工艺", "传统节气", "老字号"]'),
    )
    kws = await keyword_extractor._extract_via_llm(_spec(), fake_llm)
    assert kws == ["非遗手工艺", "传统节气", "老字号"]


@pytest.mark.asyncio
async def test_extract_via_llm_strips_markdown_code_block() -> None:
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse(
            '```json\n["非遗手工艺", "传统节气", "老字号"]\n```'
        ),
    )
    kws = await keyword_extractor._extract_via_llm(_spec(), fake_llm)
    assert kws == ["非遗手工艺", "传统节气", "老字号"]


@pytest.mark.asyncio
async def test_extract_via_llm_falls_back_on_llm_error() -> None:
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        side_effect=RuntimeError("API timeout"),
    )
    kws = await keyword_extractor._extract_via_llm(_spec(), fake_llm)
    assert kws == _fallback_keywords(_spec())


@pytest.mark.asyncio
async def test_extract_via_llm_falls_back_on_invalid_json() -> None:
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse("not json at all"),
    )
    kws = await keyword_extractor._extract_via_llm(_spec(), fake_llm)
    assert kws == _fallback_keywords(_spec())


@pytest.mark.asyncio
async def test_extract_via_llm_truncates_to_n_keywords() -> None:
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["a", "b", "c", "d", "e", "f"]'),
    )
    kws = await keyword_extractor._extract_via_llm(_spec(), fake_llm)
    assert len(kws) == 3
