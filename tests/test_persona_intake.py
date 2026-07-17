import json
from pathlib import Path

from heated_topics_v3.persona_intake import RegisteredPersona, register_persona


def _fake_structurer(prompt: str, *, system: str | None = None, **_kwargs) -> str:
    return json.dumps(
        {
            "role": "理财入门博主",
            "subject": "个人理财",
            "scenarios": ["基金", "存款", "记账"],
            "value": "给普通人可落地的理财建议",
        },
        ensure_ascii=False,
    )


def _fake_keyword(prompt: str, *, system: str | None = None, **_kwargs) -> str:
    tiers = ["热榜"] * 5 + ["长尾"] * 4 + ["兜底"]
    return json.dumps(
        [{"keyword": f"kw{i}", "match_expectation": tiers[i]} for i in range(10)],
        ensure_ascii=False,
    )


def _run(tmp_path, *, level2="普通人理财", use_llm=True, core_keywords=None):
    return register_persona(
        "财经",
        level2,
        "普通人理财博主，分享基金、存款、记账，帮小白避坑",
        profiles_dir=tmp_path / "profiles",
        keyword_cache_dir=tmp_path / "cache",
        core_keywords=core_keywords,
        use_llm=use_llm,
        structurer_llm=_fake_structurer,
        keyword_llm=_fake_keyword,
    )


def test_register_returns_registered_persona(tmp_path: Path):
    result = _run(tmp_path)
    assert isinstance(result, RegisteredPersona)
    assert result.user_id == "licai_001"
    assert result.profile_path.exists()


def test_register_writes_valid_profile_json(tmp_path: Path):
    result = _run(tmp_path)
    payload = json.loads(result.profile_path.read_text(encoding="utf-8"))
    assert payload["user_id"] == "licai_001"
    assert payload["level1"] == "财经"
    assert payload["level2"] == "普通人理财"
    assert payload["personal"]["role"] == "理财入门博主"
    assert payload["personal"]["scenarios"] == ["基金", "存款", "记账"]
    assert payload["core_keywords"]  # non-empty


def test_register_profile_is_loadable(tmp_path: Path):
    result = _run(tmp_path)
    # register_persona loads it back through the validator; expose that profile.
    assert result.profile.user_id == "licai_001"
    assert result.profile.personal.subject == "个人理财"
    assert result.profile.persona_signature  # computed


def test_register_extracts_and_caches_keywords(tmp_path: Path):
    result = _run(tmp_path)
    assert len(result.keywords) == 10
    assert result.keywords[0].keyword == "kw0"
    cache_file = tmp_path / "cache" / "licai_001.json"
    assert cache_file.exists()


def test_second_same_level2_gets_next_id(tmp_path: Path):
    first = _run(tmp_path)
    second = _run(tmp_path)
    assert first.user_id == "licai_001"
    assert second.user_id == "licai_002"
    assert second.profile_path.exists()


def test_core_keywords_override_respected(tmp_path: Path):
    result = _run(tmp_path, core_keywords=["比特币", "美联储"])
    payload = json.loads(result.profile_path.read_text(encoding="utf-8"))
    assert payload["core_keywords"] == ["比特币", "美联储"]


def test_use_llm_false_skips_llm_and_still_writes(tmp_path: Path):
    calls: list[str] = []

    def tracking_structurer(prompt: str, *, system: str | None = None, **_kwargs) -> str:
        calls.append("structurer")
        return _fake_structurer(prompt, system=system)

    def tracking_keyword(prompt: str, *, system: str | None = None, **_kwargs) -> str:
        calls.append("keyword")
        return _fake_keyword(prompt, system=system)

    result = register_persona(
        "财经",
        "普通人理财",
        "普通人理财博主，分享基金、存款、记账",
        profiles_dir=tmp_path / "profiles",
        keyword_cache_dir=tmp_path / "cache",
        use_llm=False,
        structurer_llm=tracking_structurer,
        keyword_llm=tracking_keyword,
    )
    assert calls == []  # no LLM touched
    assert result.profile_path.exists()
    assert result.profile.core_keywords  # heuristic core keywords non-empty
    assert result.keywords  # synthesized from core keywords


def test_blank_input_raises(tmp_path: Path):
    import pytest

    with pytest.raises(ValueError):
        register_persona(
            "财经",
            "  ",
            "text",
            profiles_dir=tmp_path / "profiles",
            keyword_cache_dir=tmp_path / "cache",
        )
