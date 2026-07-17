from pathlib import Path

from heated_topics_v3.persona_slugs import (
    FALLBACK_KEYWORDS,
    LEVEL2_SLUG,
    assign_user_id,
)


def _touch(profiles_dir: Path, stem: str) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{stem}.json").write_text("{}", encoding="utf-8")


def test_assign_first_id_in_empty_dir(tmp_path: Path):
    assert assign_user_id("普通人理财", tmp_path) == "licai_001"


def test_assign_increments_past_existing(tmp_path: Path):
    _touch(tmp_path, "licai_001")
    assert assign_user_id("普通人理财", tmp_path) == "licai_002"


def test_assign_fills_gap(tmp_path: Path):
    _touch(tmp_path, "licai_001")
    _touch(tmp_path, "licai_003")
    assert assign_user_id("普通人理财", tmp_path) == "licai_002"


def test_assign_unknown_level2_uses_persona_slug(tmp_path: Path):
    assert assign_user_id("完全没见过的赛道", tmp_path) == "persona_001"


def test_assign_ignores_other_slug_files(tmp_path: Path):
    _touch(tmp_path, "xuesheng_001")
    assert assign_user_id("普通人理财", tmp_path) == "licai_001"


def test_assign_missing_dir_returns_first(tmp_path: Path):
    assert assign_user_id("普通人理财", tmp_path / "does_not_exist") == "licai_001"


def test_mappings_are_aligned():
    # Every slug-mapped level2 should also have a fallback keyword list.
    assert set(LEVEL2_SLUG) == set(FALLBACK_KEYWORDS)
