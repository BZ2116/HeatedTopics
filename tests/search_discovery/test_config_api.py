from pathlib import Path

from src.search_discovery.config_api import run_config_api_command
from src.search_discovery.connectivity import ConnectionTestResult


def test_list_command_masks_configured_keys(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("TAVILY_API_KEY=tvly_1234567890\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = run_config_api_command(["--list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[OK]" in output
    assert "tavily_search" in output
    assert "tvly****7890" in output
    assert "tvly_1234567890" not in output


def test_set_command_saves_then_tests_connection(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("TAVILY_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["tvly_fake", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(
        "src.search_discovery.config_api.test_source_after_save",
        lambda source_id, root: ConnectionTestResult(
            source_id=source_id,
            status="ok",
            message="tavily_search connected successfully, returned 2 results.",
            result_count=2,
        ),
    )

    exit_code = run_config_api_command(["--set", "tavily_search"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "TAVILY_API_KEY=tvly_fake\n"
    assert "[OK] Saved TAVILY_API_KEY" in output
    assert "[TEST] Testing tavily_search" in output
    assert "connected successfully" in output


def test_set_command_does_not_save_when_user_declines(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("TAVILY_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["tvly_fake", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    exit_code = run_config_api_command(["--set", "tavily_search"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "TAVILY_API_KEY=\n"
    assert "Cancelled" in output