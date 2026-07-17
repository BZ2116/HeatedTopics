import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import heated_topics_v3.cli as cli
from heated_topics_v3.hot_board_cache import utc8_today

V2_PROFILE = {
    "user_id": "zhao_001",
    "level1": "科技AI",
    "level2": "AI工具应用",
    "personal": {
        "role": "AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习"],
        "value": "真实建议",
    },
    "core_keywords": ["AI工具"],
}


def _write_profile(tmp_path: Path) -> Path:
    path = tmp_path / "zhao_001.json"
    path.write_text(json.dumps(V2_PROFILE, ensure_ascii=False), encoding="utf-8")
    return path


def _fake_result(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=tmp_path / "run",
        report_path=tmp_path / "run" / "report.md",
        focused_path=tmp_path / "run" / "focused.json",
        kept_total=1,
        candidates_total=1,
        paths={"A": 1},
        hot_board_source="cache",
        keyword_source="custom",
    )


def test_cli_quota_exceeded_prints_message_exit_2(tmp_path, monkeypatch, capsys):
    profile_path = _write_profile(tmp_path)
    # Seed quota at the limit (3).
    quota_dir = tmp_path / "state" / "quota"
    quota_dir.mkdir(parents=True)
    (quota_dir / "zhao_001.json").write_text(
        json.dumps({"date": utc8_today(), "count": 3}), encoding="utf-8"
    )

    called = {"pipeline": False}

    def stub_pipeline(*_args, **_kwargs):
        called["pipeline"] = True
        return _fake_result(tmp_path)

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", stub_pipeline)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "toutiao", "--profile-v2", str(profile_path),
         "--state-root", str(tmp_path / "state"), "--no-llm"],
    )

    with pytest.raises(SystemExit) as exc:
        cli._main()
    assert exc.value.code == 2
    assert called["pipeline"] is False
    assert "今日额度已用完" in capsys.readouterr().err


def test_cli_skip_quota_bypasses_check(tmp_path, monkeypatch, capsys):
    profile_path = _write_profile(tmp_path)
    quota_dir = tmp_path / "state" / "quota"
    quota_dir.mkdir(parents=True)
    (quota_dir / "zhao_001.json").write_text(
        json.dumps({"date": utc8_today(), "count": 3}), encoding="utf-8"
    )

    captured = {}

    def stub_pipeline(*_args, **kwargs):
        captured.update(kwargs)
        return _fake_result(tmp_path)

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", stub_pipeline)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "toutiao", "--profile-v2", str(profile_path),
         "--state-root", str(tmp_path / "state"), "--skip-quota", "--no-llm"],
    )

    cli._main()
    # Pipeline ran despite quota being at the limit, and no commit callback wired.
    assert captured.get("on_search_committed") is None


def test_cli_custom_keyword_passed_to_pipeline(tmp_path, monkeypatch):
    profile_path = _write_profile(tmp_path)
    captured = {}

    def stub_pipeline(*_args, **kwargs):
        captured.update(kwargs)
        return _fake_result(tmp_path)

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", stub_pipeline)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "toutiao", "--profile-v2", str(profile_path),
         "--state-root", str(tmp_path / "state"), "--skip-quota", "--no-llm",
         "--custom-keyword", "比特币", "--custom-keyword", " ",
         "--custom-keyword", "美联储"],
    )

    cli._main()
    # Blank keyword is stripped out; order preserved.
    assert captured.get("custom_keywords") == ("比特币", "美联储")
