import json

import pytest

from heated_topics_v3.contracts import UserProfile
from heated_topics_v3.profiles import load_profile, save_profile


def sample_profile(**changes):
    values = {
        "user_id": "user_001",
        "primary_track": "人工智能",
        "secondary_track": "AI应用与效率工具",
        "persona": "面向普通职场人的AI工具测评博主",
        "primary_keyword": "AI工具",
        "updated_at": "2026-07-13T00:00:00+08:00",
    }
    values.update(changes)
    return UserProfile(**values)


def test_profile_json_round_trip(tmp_path):
    path = tmp_path / "profile.json"
    profile = sample_profile()

    save_profile(profile, path)

    assert load_profile(path) == profile
    assert json.loads(path.read_text(encoding="utf-8"))["primary_keyword"] == "AI工具"


@pytest.mark.parametrize("keyword", ["", "  \t\n"])
def test_profile_rejects_blank_primary_keyword(tmp_path, keyword):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({**sample_profile().__dict__, "primary_keyword": keyword}), encoding="utf-8")

    with pytest.raises(ValueError, match="primary_keyword"):
        load_profile(path)


def test_save_profile_rejects_blank_primary_keyword(tmp_path):
    with pytest.raises(ValueError, match="primary_keyword"):
        save_profile(sample_profile(primary_keyword="  "), tmp_path / "profile.json")
