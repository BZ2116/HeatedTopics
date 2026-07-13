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


@pytest.mark.parametrize(
    "user_id",
    [
        "",
        ".",
        "..",
        "../escape",
        r"..\escape",
        "/absolute",
        r"C:\escape",
        "nested/user",
        r"nested\user",
        "user:name",
        " leading",
        "a" * 65,
    ],
)
def test_user_profile_contract_rejects_unsafe_user_ids(user_id):
    with pytest.raises(ValueError, match="user_id"):
        sample_profile(user_id=user_id)


def test_profile_loader_rejects_unsafe_user_id(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({**sample_profile().__dict__, "user_id": "../../outside"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="user_id"):
        load_profile(path)


@pytest.mark.parametrize("user_id", ["u", "user_001", "smoke-user-2026", "A" * 64])
def test_user_profile_contract_accepts_safe_ascii_user_ids(user_id):
    assert sample_profile(user_id=user_id).user_id == user_id
