import json
from dataclasses import replace

import pytest

from heated_topics_v3.contracts import (
    DailySnapshot,
    PlatformCollectionStatus,
    RecommendationBundle,
)


def _json_output(capsys):
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_collect_v1_emits_machine_readable_status(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli

    observed = {}

    def fake_collect(now, repository, providers):
        observed.update(now=now, repository=repository, providers=providers)
        statuses = (
            PlatformCollectionStatus("toutiao", "success", now.isoformat(), 50),
            PlatformCollectionStatus("juejin", "partial", now.isoformat(), 30, "detail_fetch_failed:juejin_1"),
        )
        return DailySnapshot(
            now.date().isoformat(),
            now.isoformat(),
            {"toutiao": (), "juejin": ()},
            statuses,
        )

    monkeypatch.setattr(cli, "collect_v1_daily", fake_collect)

    exit_code = cli.main(["collect-v1", "--data-root", str(tmp_path)])

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["status"] == "partial"
    assert payload["command"] == "collect-v1"
    assert payload["business_date"] == observed["now"].date().isoformat()
    assert payload["data_root"] == str(tmp_path.resolve())
    assert payload["platforms"] == {
        "toutiao": {"status": "success", "item_count": 50},
        "juejin": {"status": "partial", "item_count": 30},
    }
    assert payload["elapsed_seconds"] >= 0
    assert set(observed["providers"]) == {"toutiao", "juejin"}
    assert observed["providers"]["toutiao"].rendered_fetcher is not None
    assert observed["repository"].root == tmp_path


def test_collect_v1_returns_nonzero_when_both_platforms_fail(
    monkeypatch, tmp_path, capsys
):
    from heated_topics_v3 import cli

    def failed_collect(now, repository, providers):
        statuses = tuple(
            PlatformCollectionStatus(platform, "failed", now.isoformat(), 0, "ValueError")
            for platform in ("toutiao", "juejin")
        )
        return DailySnapshot(now.date().isoformat(), now.isoformat(), {}, statuses)

    monkeypatch.setattr(cli, "collect_v1_daily", failed_collect)

    exit_code = cli.main(["collect-v1", "--data-root", str(tmp_path)])

    assert exit_code == 1
    payload = _json_output(capsys)
    assert payload["status"] == "failed"
    assert all(value["status"] == "failed" for value in payload["platforms"].values())


def test_generate_v1_loads_profile_and_emits_status(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "user_id": "smoke-user",
                "primary_track": "AI",
                "secondary_track": "developer tools",
                "persona": "technology creator",
                "primary_keyword": "OpenAI",
                "updated_at": "2026-07-13T12:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    observed = {}

    def fake_generate(profile, now, repository, toutiao_provider):
        observed.update(profile=profile, now=now, repository=repository)
        return RecommendationBundle(
            status="generated",
            user_id=profile.user_id,
            business_date=now.date().isoformat(),
            generated_at=now.isoformat(),
            recommendations=(),
            potential_topics=(),
            general_fallback=(),
            query_metadata={},
        )

    monkeypatch.setattr(cli, "generate_v1_user_result", fake_generate)

    exit_code = cli.main(
        [
            "generate-v1",
            "--data-root",
            str(tmp_path / "data"),
            "--profile",
            str(profile_path),
        ]
    )

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["status"] == "generated"
    assert payload["command"] == "generate-v1"
    assert payload["user_id"] == "smoke-user"
    assert payload["recommendation_count"] == 0
    assert payload["potential_topic_count"] == 0
    assert payload["result_dir"] == str(
        (tmp_path / "data" / "user_results" / "smoke-user" / payload["business_date"]).resolve()
    )
    assert payload["elapsed_seconds"] >= 0
    assert observed["profile"].primary_keyword == "OpenAI"


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ([], "invalid_arguments"),
        (["collect-v1"], "invalid_arguments"),
        (["generate-v1", "--data-root", "data"], "invalid_arguments"),
    ],
)
def test_invalid_arguments_return_json_failure(arguments, error, capsys):
    from heated_topics_v3 import cli

    exit_code = cli.main(arguments)

    assert exit_code == 2
    assert _json_output(capsys) == {"status": "failed", "error": error}


def test_help_uses_normal_success_exit_without_failure_json(capsys):
    from heated_topics_v3 import cli

    exit_code = cli.main(["collect-v1", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage: heated-topics collect-v1" in captured.out
    assert '"status":"failed"' not in captured.out
    assert captured.err == ""


def test_runtime_failure_is_sanitized(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli

    secret = "Bearer should-never-appear"

    def failing_collect(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "collect_v1_daily", failing_collect)

    exit_code = cli.main(["collect-v1", "--data-root", str(tmp_path)])

    assert exit_code == 1
    output = _json_output(capsys)
    assert output == {
        "status": "failed",
        "command": "collect-v1",
        "error": "RuntimeError",
    }
    assert secret not in json.dumps(output)


def test_unsuccessful_generation_status_returns_nonzero(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "user_id": "user",
                "primary_track": "AI",
                "secondary_track": "tools",
                "persona": "creator",
                "primary_keyword": "AI",
                "updated_at": "2026-07-13T12:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )

    def not_ready(profile, now, repository, toutiao_provider):
        bundle = RecommendationBundle(
            "generated", profile.user_id, now.date().isoformat(), now.isoformat(), (), (), (), {}
        )
        return replace(bundle, status="not_ready")

    monkeypatch.setattr(cli, "generate_v1_user_result", not_ready)

    exit_code = cli.main(
        ["generate-v1", "--data-root", str(tmp_path), "--profile", str(profile_path)]
    )

    assert exit_code == 1
    assert _json_output(capsys)["status"] == "not_ready"
