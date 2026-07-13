from pathlib import Path
from types import SimpleNamespace

import pytest

from heated_topics_v3 import cli


def _v2_result() -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=Path("outputs/users/zhao_001/2026-07-13/run_120000"),
        report_path=Path("outputs/users/zhao_001/2026-07-13/run_120000/report.md"),
        focused_path=Path("outputs/users/zhao_001/2026-07-13/run_120000/focused.json"),
        candidates_total=12,
        kept_total=7,
        paths={"A": 2, "B": 10},
        hot_board_source="cache",
        keyword_source="fresh",
    )


def test_toutiao_profile_v2_dispatches_all_options(monkeypatch, capsys):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _v2_result()

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "heated-topics",
            "toutiao",
            "--profile-v2",
            "config/profiles/zhao_001.json",
            "--output-root",
            "output",
            "--fetched-at",
            "2026-07-13T10:00:00+08:00",
            "--cache-root",
            "cache-data",
            "--top-n",
            "7",
            "--llm-keywords",
            "--llm-summary",
            "--llm-rerank",
            "--force-hot-board-refresh",
            "--offline",
        ],
    )

    cli._main()

    assert captured == {
        "profile_path": Path("config/profiles/zhao_001.json"),
        "output_root": Path("output"),
        "fetched_at": "2026-07-13T10:00:00+08:00",
        "hot_board_cache_root": Path("cache-data"),
        "persona_keyword_cache_root": Path("cache-data/core_keywords"),
        "llm_cache_root": Path("cache-data/llm"),
        "use_llm_keywords": True,
        "use_llm_summary": True,
        "use_llm_rerank": True,
        "force_hot_board_refresh": True,
        "offline": True,
        "top_n": 7,
    }
    output = capsys.readouterr().out
    assert "report: outputs" in output
    assert "candidates: 7/12" in output


def test_toutiao_profile_v2_no_llm_disables_all_llm_features(monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _v2_result()

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "heated-topics",
            "toutiao",
            "--profile-v2",
            "profile.json",
            "--no-llm",
        ],
    )

    cli._main()

    assert captured["use_llm_keywords"] is False
    assert captured["use_llm_summary"] is False
    assert captured["use_llm_rerank"] is False


def test_toutiao_profile_keeps_legacy_dispatch(monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"report": Path("outputs/report.md")}

    monkeypatch.setattr(cli, "run_toutiao_pipeline", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["heated-topics", "toutiao", "--profile", "legacy.json", "--output-root", "output"],
    )

    cli._main()

    assert captured["profile_path"] == Path("legacy.json")
    assert captured["output_root"] == Path("output")


def test_main_prints_v2_profile_errors(monkeypatch, capsys):
    def fake_run(**_kwargs):
        raise ValueError("profile.json uses legacy v1 schema; please migrate to v2")

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["heated-topics", "toutiao", "--profile-v2", "profile.json"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "legacy v1 schema" in capsys.readouterr().err
