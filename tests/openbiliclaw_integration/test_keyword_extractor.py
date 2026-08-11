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
    old_spec = _spec(track_1="非遗", persona="旧人设")
    _save_cache(tmp_path, old_spec, ["old1", "old2", "old3"])
    # New spec shares "非遗" with old (will match anchor).
    new_spec = _spec(track_1="非遗扩展", persona="新人设")
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["非遗新1", "非遗新2", "非遗新3"]'),
    )
    kws = await keyword_extractor.extract_or_load(new_spec, fake_llm, tmp_path)
    assert kws == ["非遗新1", "非遗新2", "非遗新3"]
    cached = _load_cache(tmp_path, new_spec)
    assert cached == ["非遗新1", "非遗新2", "非遗新3"]


@pytest.mark.asyncio
async def test_extract_or_load_writes_cache_on_miss(tmp_path: Path) -> None:
    spec = _spec()
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["非遗a", "b", "c"]'),
    )
    kws = await keyword_extractor.extract_or_load(spec, fake_llm, tmp_path)
    assert kws == ["非遗a", "b", "c"]
    fake_llm.complete_with_core_memory = AsyncMock(
        side_effect=AssertionError("cache should hit"),
    )
    again = await keyword_extractor.extract_or_load(spec, fake_llm, tmp_path)
    assert again == ["非遗a", "b", "c"]


# --- anchor-term constraint (v2.1.1) ---


def test_extract_anchor_terms_picks_frequent_substrings() -> None:
    spec = _spec(
        track_1="文化生活",
        track_2="非遗与民俗",
        persona="喜欢研究地方习俗、节气、非遗和老手艺",
    )
    anchors = keyword_extractor._extract_anchor_terms(spec)
    assert "非遗" in anchors
    # track_1 (文化生活) appears once; persona (地方习俗/节气/老手艺) each once;
    # 非遗 appears in both track_2 AND persona → should rank high.
    assert anchors.index("非遗") < anchors.index("文化生活") or "文化生活" not in anchors


def test_extract_anchor_terms_caps_at_top_n() -> None:
    spec = _spec(persona="a、b、c、d、e、f、g、h、i")
    anchors = keyword_extractor._extract_anchor_terms(spec)
    assert len(anchors) <= keyword_extractor._ANCHOR_MAX


def test_extract_anchor_terms_handles_empty_spec() -> None:
    spec = _spec(track_1="x", track_2="", persona="")
    anchors = keyword_extractor._extract_anchor_terms(spec)
    assert anchors == []


@pytest.mark.asyncio
async def test_extract_via_llm_enforces_min_anchor_locally() -> None:
    """If the LLM ignores the anchor constraint, we pad from anchors."""
    spec = _spec(
        track_1="文化生活",
        track_2="非遗与民俗",
        persona="研究非遗",
    )
    fake_llm = AsyncMock()
    # LLM returns zero anchored keywords (all invented).
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["赶集文化", "节气饮食", "老字号"]'),
    )
    kws = await keyword_extractor._extract_via_llm(spec, fake_llm, n=3)
    assert len(kws) == 3
    # At least 1 must now contain an anchor (非遗 or 文化生活).
    anchored = [
        kw for kw in kws
        if any(a in kw for a in keyword_extractor._extract_anchor_terms(spec))
    ]
    assert len(anchored) >= 1


@pytest.mark.asyncio
async def test_extract_via_llm_passes_anchors_in_prompt() -> None:
    """Anchors must be surfaced in the user prompt so the LLM sees them."""
    spec = _spec(
        track_1="非遗与民俗",
        track_2="传统文化",
        persona="研究非遗",
    )
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["非遗手工艺", "节气", "老字号"]'),
    )
    await keyword_extractor._extract_via_llm(spec, fake_llm, n=3)
    call_kwargs = fake_llm.complete_with_core_memory.call_args.kwargs
    user_input = call_kwargs["user_input"]
    assert "非遗" in user_input
    # system prompt also references min_anchor count
    assert "至少 1 个" in call_kwargs["system_instruction"]


@pytest.mark.asyncio
async def test_extract_via_llm_skips_anchor_when_no_anchors() -> None:
    """Track_1 'x' (no real anchors) → no anchor constraint."""
    spec = _spec(track_1="x", track_2="", persona="")
    fake_llm = AsyncMock()
    fake_llm.complete_with_core_memory = AsyncMock(
        return_value=_FakeResponse('["a", "b", "c"]'),
    )
    kws = await keyword_extractor._extract_via_llm(spec, fake_llm, n=3)
    assert kws == ["a", "b", "c"]
