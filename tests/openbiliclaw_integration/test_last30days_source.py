"""Subprocess wrapper tests — mock at subprocess.run boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from heated_topics_v3.openbiliclaw_integration import last30days_source


def test_run_invokes_cli_with_expected_flags(tmp_path: Path) -> None:
    fake_stdout = json.dumps({"topic": "测试", "weibo": []})
    fake_json_path = tmp_path / "report.json"
    fake_json_path.write_text(fake_stdout, encoding="utf-8")

    fake_cli = tmp_path / "last30days.py"
    with patch.object(last30days_source, "_run_subprocess") as mock_run:
        mock_run.return_value = fake_json_path
        out = last30days_source.run(
            cli_path=fake_cli,
            query="测试",
            days=30,
            save_dir=tmp_path,
            fetch_bodies=True,
            platforms=("weibo", "zhihu"),
            timeout=60,
        )
    assert out == fake_json_path
    cmd = mock_run.call_args.args[0]
    # First arg is sys.executable; second is the CLI path (any string form)
    assert cmd[0] == sys.executable
    assert cmd[1] == str(fake_cli)
    # topic is positional (3rd arg)
    assert cmd[2] == "测试"
    assert "--days" in cmd and "30" in cmd
    assert "--fetch-bodies" in cmd
    assert "--search" in cmd and "weibo,zhihu" in cmd
    assert "--emit" in cmd and "json" in cmd
    assert "--save-dir" in cmd and str(tmp_path) in cmd
    assert "--timeout" in cmd


def test_run_raises_on_missing_output(tmp_path: Path) -> None:
    with patch.object(last30days_source, "_run_subprocess") as mock_run:
        mock_run.return_value = tmp_path / "does_not_exist.json"
        try:
            last30days_source.run(
                cli_path=Path("/fake/last30days.py"),
                query="x", days=7, save_dir=tmp_path,
                fetch_bodies=False, platforms=(), timeout=30,
            )
        except last30days_source.Last30DaysSourceError:
            return
    raise AssertionError("expected Last30DaysSourceError")


def test_run_subprocess_passes_cwd_as_save_dir(tmp_path: Path) -> None:
    """subprocess.run must be invoked with cwd=str(save_dir)."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = '{"weibo": []}'
        mock_run.return_value.stderr = ""
        (tmp_path / "report.json").write_text("{}", encoding="utf-8")
        last30days_source._run_subprocess(
            [str(tmp_path / "x.py"), "--emit", "json"],
            save_dir=tmp_path,
            timeout=30,
        )
    assert mock_run.call_args.kwargs.get("cwd") == str(tmp_path)
    assert mock_run.call_args.kwargs.get("capture_output") is True
    assert mock_run.call_args.kwargs.get("text") is True


def test_run_subprocess_passes_utf8_encoding(tmp_path: Path) -> None:
    """On Windows, text=True alone uses GBK; we must force utf-8 so the
    last30days CLI's UTF-8 stdout (Chinese content) decodes correctly.
    Regression: see UnicodeDecodeError in live run."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = '{"weibo": []}'
        mock_run.return_value.stderr = ""
        last30days_source._run_subprocess(
            [str(tmp_path / "x.py"), "--emit", "json"],
            save_dir=tmp_path,
            timeout=30,
        )
    assert mock_run.call_args.kwargs.get("encoding") == "utf-8"


def test_run_subprocess_writes_stdout_to_report_json(tmp_path: Path) -> None:
    """stdout from the CLI must be persisted to <save_dir>/report.json."""
    fake_json = json.dumps({"topic": "测试", "weibo": [{"id": "WB1"}]})
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = fake_json
        mock_run.return_value.stderr = ""
        out = last30days_source._run_subprocess(
            [str(tmp_path / "x.py"), "--emit", "json"],
            save_dir=tmp_path,
            timeout=30,
        )
    assert out == tmp_path / "report.json"
    assert out.read_text(encoding="utf-8") == fake_json


def test_run_subprocess_raises_on_nonzero_exit(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "boom"
        try:
            last30days_source._run_subprocess(
                [str(tmp_path / "x.py")], save_dir=tmp_path, timeout=30,
            )
        except last30days_source.Last30DaysSourceError as exc:
            assert "boom" in str(exc) or "exited 1" in str(exc)
            return
    raise AssertionError("expected Last30DaysSourceError")


def test_run_subprocess_raises_on_timeout(tmp_path: Path) -> None:
    import subprocess as sp
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = sp.TimeoutExpired(cmd=["x"], timeout=30)
        try:
            last30days_source._run_subprocess(
                [str(tmp_path / "x.py")], save_dir=tmp_path, timeout=30,
            )
        except last30days_source.Last30DaysSourceError as exc:
            assert "timed out" in str(exc).lower()
            return
    raise AssertionError("expected Last30DaysSourceError")


def test_parse_report_minimal(tmp_path: Path) -> None:
    fake = tmp_path / "r.json"
    fake.write_text(json.dumps({"weibo": [], "topic": "x"}), encoding="utf-8")
    data = last30days_source.parse_report(fake)
    assert data["topic"] == "x"
    assert data["weibo"] == []


def test_parse_report_raises_on_missing_file(tmp_path: Path) -> None:
    try:
        last30days_source.parse_report(tmp_path / "nope.json")
    except last30days_source.Last30DaysParseError:
        return
    raise AssertionError("expected Last30DaysParseError")


def test_parse_report_raises_on_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    try:
        last30days_source.parse_report(bad)
    except last30days_source.Last30DaysParseError:
        return
    raise AssertionError("expected Last30DaysParseError")


def test_parse_report_raises_on_non_object_top_level(tmp_path: Path) -> None:
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    try:
        last30days_source.parse_report(arr)
    except last30days_source.Last30DaysParseError:
        return
    raise AssertionError("expected Last30DaysParseError")


def test_exceptions_module_exposes_both_classes() -> None:
    """Caller can catch either error category via last30days_source.X."""
    assert issubclass(
        last30days_source.Last30DaysParseError,
        last30days_source.Last30DaysSourceError,
    )