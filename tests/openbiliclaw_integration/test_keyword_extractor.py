"""Tests for LLM-driven keyword extraction + per-user cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from heated_topics_v3.openbiliclaw_integration import keyword_extractor
from heated_topics_v3.openbiliclaw_integration.keyword_extractor import (
    _fallback_keywords,
    _load_cache,
    _save_cache,
)
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


@pytest.mark.asyncio
async def test_extract_or_load_returns_cached_when_hash_matches(tmp_path: Path) -> None:
    spec = _spec()
    _save_cache(tmp_path, spec, ["非遗手工艺", "节气", "老字号"])
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        side_effect=AssertionError("LLM should NOT be called on cache hit"),
    )
    kws = await keyword_extractor.extract_or_load(spec, fake_llm, tmp_path)
    assert kws == ["非遗手工艺", "节气", "老字号"]


@pytest.mark.asyncio
async def test_extract_or_load_re_extracts_when_spec_changes(tmp_path: Path) -> None:
    old_spec = _spec(track_1="旧赛道", persona="旧人设")
    _save_cache(tmp_path, old_spec, ["old1", "old2", "old3"])
    new_spec = _spec(track_1="新赛道", persona="新人设")
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["新1", "新2", "新3"]'),
    )
    kws = await keyword_extractor.extract_or_load(new_spec, fake_llm, tmp_path)
    assert kws == ["新1", "新2", "新3"]
    cached = _load_cache(tmp_path, new_spec)
    assert cached == ["新1", "新2", "新3"]


@pytest.mark.asyncio
async def test_extract_or_load_writes_cache_on_miss(tmp_path: Path) -> None:
    spec = _spec()
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["a", "b", "c"]'),
    )
    kws = await keyword_extractor.extract_or_load(spec, fake_llm, tmp_path)
    assert kws == ["a", "b", "c"]
    fake_llm.complete_with_core_memory = AsyncMock(
        side_effect=AssertionError("cache should hit"),
    )
    again = await keyword_extractor.extract_or_load(spec, fake_llm, tmp_path)
    assert again == ["a", "b", "c"]
