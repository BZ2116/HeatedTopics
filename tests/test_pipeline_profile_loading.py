import json

from heated_topics_v3.pipeline import load_user_profile


def test_load_user_profile_accepts_utf8_bom(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "windows_profile",
                "display_name": "Windows Profile",
                "domains": ["social"],
                "audience": ["creator"],
                "content_modes": ["hot topics"],
                "preferred_platforms": ["weibo"],
                "core_keywords": ["台风"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    profile = load_user_profile(profile_path)

    assert profile.profile_id == "windows_profile"
    assert profile.core_keywords == ("台风",)
