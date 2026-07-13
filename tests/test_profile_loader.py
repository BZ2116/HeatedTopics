import json
from pathlib import Path

import pytest

from heated_topics_v3.profile_loader import (
    PersonaProfile,
    ProfileSchemaError,
    compute_persona_signature,
    is_legacy_profile,
    load_persona_profile,
)


V2_EXAMPLE = {
    "user_id": "zhao_001",
    "level1": "科技AI",
    "level2": "AI工具应用",
    "personal": {
        "role": "经管学生视角的AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习", "办公", "内容生产"],
        "value": "真实使用建议",
    },
    "core_keywords": ["AI工具", "AI写作", "AI办公", "AI学习"],
}


LEGACY_EXAMPLE = {
    "profile_id": "tech_ai_creator",
    "display_name": "Tech AI Creator",
    "domains": ["tech", "ai"],
    "audience": ["developers"],
    "content_modes": ["analysis"],
    "preferred_platforms": ["toutiao"],
    "core_keywords": ["AI Agent", "MCP"],
    "entity_keywords": ["Claude Code"],
    "excluded_keywords": ["unverified rumor"],
}


def test_load_persona_profile_accepts_v2_schema(tmp_path: Path):
    profile_path = tmp_path / "zhao_001.json"
    profile_path.write_text(json.dumps(V2_EXAMPLE, ensure_ascii=False), encoding="utf-8")
    profile = load_persona_profile(profile_path)
    assert isinstance(profile, PersonaProfile)
    assert profile.user_id == "zhao_001"
    assert profile.level1 == "科技AI"
    assert profile.level2 == "AI工具应用"
    assert profile.personal.role == "经管学生视角的AI工具体验官"
    assert profile.personal.subject == "AI工具"
    assert profile.personal.scenarios == ("写作", "学习", "办公", "内容生产")
    assert profile.personal.value == "真实使用建议"
    assert profile.core_keywords == ("AI工具", "AI写作", "AI办公", "AI学习")
    assert len(profile.persona_signature) == 16


def test_load_persona_profile_rejects_legacy_flat_schema(tmp_path: Path):
    profile_path = tmp_path / "legacy.json"
    profile_path.write_text(json.dumps(LEGACY_EXAMPLE, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProfileSchemaError) as exc_info:
        load_persona_profile(profile_path)
    msg = str(exc_info.value)
    assert "legacy" in msg.lower()
    assert "display_name" in msg or "domains" in msg or "audience" in msg
    assert "user_id" in msg and "core_keywords" in msg


def test_is_legacy_profile_detects_v1(tmp_path: Path):
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(LEGACY_EXAMPLE, ensure_ascii=False), encoding="utf-8")
    assert is_legacy_profile(legacy_path) is True

    v2_path = tmp_path / "v2.json"
    v2_path.write_text(json.dumps(V2_EXAMPLE, ensure_ascii=False), encoding="utf-8")
    assert is_legacy_profile(v2_path) is False


def test_persona_signature_changes_when_personal_changes(tmp_path: Path):
    profile_a = tmp_path / "a.json"
    profile_b = tmp_path / "b.json"
    profile_a.write_text(json.dumps(V2_EXAMPLE, ensure_ascii=False), encoding="utf-8")
    payload_b = json.loads(json.dumps(V2_EXAMPLE))
    payload_b["personal"]["subject"] = "AI Agent"
    profile_b.write_text(json.dumps(payload_b, ensure_ascii=False), encoding="utf-8")

    pa = load_persona_profile(profile_a)
    pb = load_persona_profile(profile_b)
    assert pa.persona_signature != pb.persona_signature


def test_load_persona_profile_reads_utf8_bom(tmp_path: Path):
    profile_path = tmp_path / "bom.json"
    profile_path.write_bytes(b"\xef\xbb\xbf" + json.dumps(V2_EXAMPLE, ensure_ascii=False).encode("utf-8"))
    profile = load_persona_profile(profile_path)
    assert profile.user_id == "zhao_001"


def test_compute_persona_signature_is_deterministic_and_short():
    from heated_topics_v3.contracts import PersonaPersonal

    personal = PersonaPersonal(
        role="r", subject="s", scenarios=("x", "y"), value="v",
    )
    sig1 = compute_persona_signature("L1", "L2", personal)
    sig2 = compute_persona_signature("L1", "L2", personal)
    assert sig1 == sig2
    assert len(sig1) == 16


def test_load_persona_profile_rejects_missing_required_fields(tmp_path: Path):
    for missing in ("user_id", "level1", "level2", "personal", "core_keywords"):
        payload = json.loads(json.dumps(V2_EXAMPLE))
        payload.pop(missing)
        path = tmp_path / f"missing_{missing}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ProfileSchemaError) as exc_info:
            load_persona_profile(path)
        assert missing in str(exc_info.value)


def test_load_persona_profile_rejects_empty_scenarios(tmp_path: Path):
    payload = json.loads(json.dumps(V2_EXAMPLE))
    payload["personal"]["scenarios"] = []
    path = tmp_path / "empty_scenarios.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProfileSchemaError) as exc_info:
        load_persona_profile(path)
    assert "scenarios" in str(exc_info.value)


def test_load_persona_profile_rejects_empty_core_keywords(tmp_path: Path):
    payload = json.loads(json.dumps(V2_EXAMPLE))
    payload["core_keywords"] = []
    path = tmp_path / "empty_kw.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProfileSchemaError) as exc_info:
        load_persona_profile(path)
    assert "core_keywords" in str(exc_info.value)