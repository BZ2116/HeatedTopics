from pathlib import Path

from src.search_discovery.api_config import ApiSourceConfig
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


def test_set_command_with_skip_test_does_not_run_connection(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("TAVILY_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["tvly_fake", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    test_calls: list[str] = []

    def fake_test(source_id, root):
        test_calls.append(source_id)
        return ConnectionTestResult(source_id=source_id, status="ok", message="ok", result_count=1)

    monkeypatch.setattr("src.search_discovery.config_api.test_source_after_save", fake_test)

    exit_code = run_config_api_command(["--set", "tavily_search", "--no-test-after-set"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert test_calls == []
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "TAVILY_API_KEY=tvly_fake\n"
    assert "[OK] Saved TAVILY_API_KEY" in output
    assert "[SKIP]" in output
    assert "[TEST]" not in output


def test_wizard_command_with_skip_test_skips_all_connections(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("GITHUB_TOKEN=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["ghp_fake", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    test_calls: list[str] = []

    def fake_test(source_id, root):
        test_calls.append(source_id)
        return ConnectionTestResult(source_id=source_id, status="ok", message="ok", result_count=1)

    monkeypatch.setattr("src.search_discovery.config_api.test_source_after_save", fake_test)

    def minimal_configs() -> dict[str, ApiSourceConfig]:
        return {
            "github_search": ApiSourceConfig(
                source_id="github_search",
                display_name="GitHub Search",
                env_keys=["GITHUB_TOKEN"],
                signup_url="https://github.com/settings/tokens",
                description="test",
            ),
        }

    monkeypatch.setattr("src.search_discovery.config_api.api_source_configs", minimal_configs)

    exit_code = run_config_api_command(["--wizard", "--no-test-after-wizard"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert test_calls == []
    assert "[SKIP]" in output
    assert "[TEST]" not in output