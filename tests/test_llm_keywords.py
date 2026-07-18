import json
from pathlib import Path

import pytest

from heated_topics_v3.contracts import PersonaPersonal, PersonaProfile
from heated_topics_v3.llm_client import LLMUnavailable
from heated_topics_v3.llm_keywords import (
    DEFAULT_CACHE_DIR,
    KEYWORD_EXTRACTION_SYSTEM,
    MIN_KEYWORDS,
    _build_prompt,
    _parse_keywords,
    extract_persona_keywords,
)


def _by_tier(keywords):
    out = {"热榜": [], "长尾": [], "兜底": []}
    for k in keywords:
        out[k.match_expectation].append(k.keyword)
    return out


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


def test_keyword_prompt_prioritizes_relevance_then_heat():
    prompt = _build_prompt(_profile())

    assert "3-10" in prompt
    assert "相关性是硬约束" in KEYWORD_EXTRACTION_SYSTEM
    assert "热度" in KEYWORD_EXTRACTION_SYSTEM
    assert "不要求在原始字段中原样出现" in KEYWORD_EXTRACTION_SYSTEM
    assert "优先 2-3 个字符" in KEYWORD_EXTRACTION_SYSTEM
    assert "专有实体" in KEYWORD_EXTRACTION_SYSTEM


def test_three_valid_keywords_do_not_retry(tmp_path: Path):
    calls = []

    def fake_llm(prompt: str, **_kwargs):
        calls.append(prompt)
        return json.dumps(
            [
                {"keyword": "大模型", "match_expectation": "热榜"},
                {"keyword": "OpenAI", "match_expectation": "热榜"},
                {"keyword": "智能体", "match_expectation": "热榜"},
            ],
            ensure_ascii=False,
        )

    result = extract_persona_keywords(
        _profile(), cache_dir=tmp_path / "kw", use_cache=False, llm=fake_llm,
    )

    assert len(calls) == 1
    assert MIN_KEYWORDS == 3
    assert [item.keyword for item in result.keywords] == ["大模型", "OpenAI", "智能体"]


def test_two_valid_keywords_retry_with_feedback(tmp_path: Path):
    calls = []
    responses = iter(
        [
            [
                {"keyword": "大模型", "match_expectation": "热榜"},
                {"keyword": "智能体", "match_expectation": "热榜"},
            ],
            [
                {"keyword": "大模型", "match_expectation": "热榜"},
                {"keyword": "智能体", "match_expectation": "热榜"},
                {"keyword": "OpenAI", "match_expectation": "热榜"},
            ],
        ]
    )

    def fake_llm(prompt: str, **_kwargs):
        calls.append(prompt)
        return json.dumps(next(responses), ensure_ascii=False)

    result = extract_persona_keywords(
        _profile(), cache_dir=tmp_path / "kw", use_cache=False, llm=fake_llm,
    )

    assert len(calls) == 2
    assert "上一次仅得到 2 个有效关键词" in calls[1]
    assert len(result.keywords) == 3


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (3, (3, 0, 0)),
        (4, (4, 0, 0)),
        (5, (5, 0, 0)),
        (6, (5, 1, 0)),
        (7, (5, 2, 0)),
        (8, (5, 3, 0)),
        (9, (5, 4, 0)),
        (10, (5, 4, 1)),
    ],
)
def test_parse_keywords_uses_hot_first_tiers(count, expected):
    raw = json.dumps(
        [
            {"keyword": f"词{i}", "match_expectation": "热榜"}
            for i in range(count)
        ],
        ensure_ascii=False,
    )

    result = _parse_keywords(raw)
    by_tier = _by_tier(result)

    assert tuple(len(by_tier[tier]) for tier in ("热榜", "长尾", "兜底")) == expected


def test_parse_keywords_keeps_semantic_expansions_and_long_entities():
    raw = json.dumps(
        [
            {"keyword": "大模型", "match_expectation": "热榜"},
            {"keyword": "OpenAI", "match_expectation": "热榜"},
            {"keyword": "DeepSeek", "match_expectation": "热榜"},
        ],
        ensure_ascii=False,
    )

    assert [item.keyword for item in _parse_keywords(raw)] == [
        "大模型",
        "OpenAI",
        "DeepSeek",
    ]


def test_parse_keywords_deduplicates_and_caps_at_ten():
    words = ["大模型", "大模型"] + [f"词{i}" for i in range(12)]
    raw = json.dumps(
        [
            {"keyword": word, "match_expectation": "热榜"}
            for word in words
        ],
        ensure_ascii=False,
    )

    result = _parse_keywords(raw)

    assert len(result) == 10
    assert [item.keyword for item in result].count("大模型") == 1


def test_cache_accepts_long_named_entities(tmp_path: Path):
    profile = _profile()
    cache_path = tmp_path / "kw" / f"{profile.user_id}.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "user_id": profile.user_id,
                "persona_signature": profile.persona_signature,
                "generated_at": "2026-07-17T10:00:00+08:00",
                "keywords": [
                    ["OpenAI", "热榜"],
                    ["DeepSeek", "热榜"],
                    ["大模型", "热榜"],
                ],
                "source": "fresh",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("valid cache should prevent an LLM call")

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=boom)

    assert result.source == "cache_fresh"
    assert [item.keyword for item in result.keywords] == ["OpenAI", "DeepSeek", "大模型"]


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
    assert result.source == "cache_fresh"
    assert [k.keyword for k in result.keywords] == ["AI写作", "AI办公", "AI学习", "MCP", "Cursor"]
    assert all(k.match_expectation == "热榜" for k in result.keywords)


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
    assert all(k.match_expectation == "热榜" for k in result.keywords)

    cached = extract_persona_keywords(
        profile, cache_dir=tmp_path / "kw", llm=lambda *_args, **_kwargs: "unused",
    )
    assert cached.source == "cache_fallback_core"


def test_extract_persona_keywords_reports_llm_fallback(tmp_path: Path, capsys):
    def fake_llm(*_args, **_kwargs):
        raise LLMUnavailable("HTTP 401: invalid api key")

    extract_persona_keywords(
        _profile(), cache_dir=tmp_path / "kw", llm=fake_llm, allow_llm=True,
    )

    stderr = capsys.readouterr().err
    assert "MiniMax/LLM keyword extraction failed" in stderr
    assert "HTTP 401: invalid api key" in stderr


def test_extract_persona_keywords_does_not_pad_valid_llm_output(tmp_path: Path):
    profile = _profile()

    def fake_llm(*_args, **_kwargs):
        return json.dumps(
                [
                    {"keyword": "AI写作", "match_expectation": "热榜"},
                    {"keyword": "AI办公", "match_expectation": "热榜"},
                    {"keyword": "智能体", "match_expectation": "热榜"},
                ],
            ensure_ascii=False,
        )

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=fake_llm)
    assert result.source == "fresh"
    assert [item.keyword for item in result.keywords] == ["AI写作", "AI办公", "智能体"]
    by_tier = _by_tier(result.keywords)
    assert len(by_tier["热榜"]) == 3
    assert len(by_tier["长尾"]) == 0
    assert len(by_tier["兜底"]) == 0


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
    assert all(item.match_expectation == "热榜" for item in result.keywords)
