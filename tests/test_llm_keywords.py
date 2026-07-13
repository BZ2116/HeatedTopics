import json
from pathlib import Path

import pytest

from heated_topics_v3.contracts import PersonaPersonal, PersonaProfile
from heated_topics_v3.llm_client import LLMUnavailable
from heated_topics_v3.llm_keywords import (
    DEFAULT_CACHE_DIR,
    MIN_KEYWORDS,
    extract_persona_keywords,
)


def _profile(subject: str = "AI工具") -> PersonaProfile:
    from heated_topics_v3.profile_loader import compute_persona_signature

    personal = PersonaPersonal(
        role="经管学生视角的AI工具体验官",
        subject=subject,
        scenarios=("写作", "学习", "办公"),
        value="真实使用建议",
    )
    return PersonaProfile(
        user_id="zhao_001",
        level1="科技AI",
        level2="AI工具应用",
        personal=personal,
        core_keywords=("AI工具", "AI写作", "AI办公", "AI学习", "AI评测"),
        persona_signature=compute_persona_signature("科技AI", "AI工具应用", personal),
    )


def test_extract_persona_keywords_calls_llm_on_fresh_cache(tmp_path: Path):
    profile = _profile()
    calls: list[tuple[str, str | None]] = []

    def fake_llm(prompt: str, *, system: str | None = None, **_kwargs):
        calls.append((prompt, system))
        return json.dumps(
            [
                {"keyword": "AI写作工具", "match_expectation": "热榜"},
                {"keyword": "AI办公助手", "match_expectation": "长尾"},
                {"keyword": "AI学习助手", "match_expectation": "长尾"},
                {"keyword": "Claude Code", "match_expectation": "热榜"},
                {"keyword": "MCP 协议", "match_expectation": "兜底"},
                {"keyword": "Cursor", "match_expectation": "兜底"},
            ],
            ensure_ascii=False,
        )

    result = extract_persona_keywords(
        profile, cache_dir=tmp_path / "kw", llm=fake_llm,
    )

    assert len(calls) == 1
    assert calls[0][1] is not None and "persona" in calls[0][1]
    assert result.source == "fresh"
    keywords = [k.keyword for k in result.keywords]
    assert "AI写作工具" in keywords
    assert len(result.keywords) <= 10
    cache_path = tmp_path / "kw" / "zhao_001.json"
    assert cache_path.exists()


def test_extract_persona_keywords_returns_cache_when_signature_matches(tmp_path: Path):
    profile = _profile()
    cache_path = tmp_path / "kw" / "zhao_001.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "user_id": "zhao_001",
                "persona_signature": profile.persona_signature,
                "generated_at": "2026-07-13T10:00:00+08:00",
                "keywords": [
                    ["AI写作", "热榜"],
                    ["AI办公", "长尾"],
                    ["AI学习", "兜底"],
                    ["MCP", "兜底"],
                    ["Cursor", "兜底"],
                ],
                "source": "fresh",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("LLM should not be called when cache hits")

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=boom)
    assert result.source == "cache"
    assert [k.keyword for k in result.keywords] == ["AI写作", "AI办公", "AI学习", "MCP", "Cursor"]


def test_extract_persona_keywords_invalidates_cache_on_signature_change(tmp_path: Path):
    profile_a = _profile(subject="AI工具")
    cache_path = tmp_path / "kw" / "zhao_001.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "user_id": "zhao_001",
                "persona_signature": "stale_signature_xxxxxx",
                "generated_at": "2026-07-13T10:00:00+08:00",
                "keywords": [["OLD", "兜底"]] * 5,
                "source": "fresh",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_llm(prompt: str, *, system: str | None = None, **_kwargs):
        return json.dumps(
            [
                {"keyword": "AI Agent", "match_expectation": "热榜"},
                {"keyword": "智能体", "match_expectation": "长尾"},
                {"keyword": "大模型", "match_expectation": "兜底"},
                {"keyword": "MCP", "match_expectation": "兜底"},
                {"keyword": "Cursor", "match_expectation": "兜底"},
            ],
            ensure_ascii=False,
        )

    result = extract_persona_keywords(profile_a, cache_dir=tmp_path / "kw", llm=fake_llm)
    assert result.source == "fresh"
    assert "AI Agent" in [k.keyword for k in result.keywords]


def test_extract_persona_keywords_falls_back_to_core_on_llm_unavailable(tmp_path: Path):
    profile = _profile()

    def fake_llm(*_args, **_kwargs):
        raise LLMUnavailable("network down")

    result = extract_persona_keywords(
        profile, cache_dir=tmp_path / "kw", llm=fake_llm, allow_llm=True,
    )
    assert result.source == "fallback_core"
    assert [k.keyword for k in result.keywords] == list(profile.core_keywords)
    assert all(k.match_expectation == "兜底" for k in result.keywords)


def test_extract_persona_keywords_pads_short_llm_output_from_core(tmp_path: Path):
    profile = _profile()

    def fake_llm(*_args, **_kwargs):
        return json.dumps(
            [
                {"keyword": "AI写作", "match_expectation": "热榜"},
                {"keyword": "AI办公", "match_expectation": "热榜"},
            ],
            ensure_ascii=False,
        )

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=fake_llm)
    assert len(result.keywords) >= MIN_KEYWORDS
    assert result.keywords[0].keyword == "AI写作"
    assert result.keywords[1].keyword == "AI办公"
    fallback_keywords = {k.keyword for k in result.keywords[2:]}
    assert fallback_keywords.issubset(set(profile.core_keywords))


def test_extract_persona_keywords_with_allow_llm_false_uses_core(tmp_path: Path):
    profile = _profile()

    def boom(*_args, **_kwargs):
        raise AssertionError("LLM must not be called when allow_llm=False")

    result = extract_persona_keywords(
        profile, cache_dir=tmp_path / "kw", llm=boom, allow_llm=False,
    )
    assert result.source == "no_llm"
    assert [k.keyword for k in result.keywords] == list(profile.core_keywords)


def test_extract_persona_keywords_drops_invalid_llm_entries(tmp_path: Path):
    profile = _profile()

    def fake_llm(*_args, **_kwargs):
        return json.dumps(
            [
                {"keyword": "AI写作", "match_expectation": "热榜"},
                {"keyword": "", "match_expectation": "热榜"},
                {"keyword": "AI办公", "match_expectation": "未知类别"},
                {"keyword": "AI学习", "match_expectation": "兜底"},
                {"keyword": "MCP", "match_expectation": "热榜"},
                "not a dict",
            ],
            ensure_ascii=False,
        )

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=fake_llm)
    keywords = [k.keyword for k in result.keywords]
    assert "" not in keywords
    assert "AI写作" in keywords
    assert "AI学习" in keywords


def test_extract_persona_keywords_strips_code_fence(tmp_path: Path):
    profile = _profile()

    def fake_llm(*_args, **_kwargs):
        return "```json\n" + json.dumps(
            [
                {"keyword": "AI写作", "match_expectation": "热榜"},
                {"keyword": "AI办公", "match_expectation": "热榜"},
                {"keyword": "AI学习", "match_expectation": "长尾"},
                {"keyword": "MCP", "match_expectation": "兜底"},
                {"keyword": "Cursor", "match_expectation": "兜底"},
            ],
            ensure_ascii=False,
        ) + "\n```"

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=fake_llm)
    assert result.source == "fresh"
    assert len(result.keywords) == 5