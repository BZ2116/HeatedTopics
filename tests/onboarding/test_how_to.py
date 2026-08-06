"""Executable documentation — the README as pytest functions.

Each test mirrors a section of ``README.md`` / ``docs/README-*.md``.
The docstring + code together ARE the documentation; reading the test
source is enough to learn how to invoke the system.

All external I/O (V3 hot-list providers, last30days subprocess, LLM
keyword extraction, LLM summary) is auto-stubbed by
``tests/onboarding/conftest.py`` so these tests finish in a few seconds
without an API key, Ollama, or network access. They demonstrate the
public surface area only.

Run::

    pytest tests/onboarding/test_how_to.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openpyxl import Workbook

from heated_topics_v3.openbiliclaw_integration import (
    cli,
    excel_loader,
    recommender,
    report_writer,
    user_profile,
)


# ---------------------------------------------------------------------------
# Shared helpers used by the how-to tests.
# ---------------------------------------------------------------------------


def _write_xlsx(path: Path, rows: list[list[str]]) -> Path:
    """Build a 4-column users.xlsx with the canonical header."""
    wb = Workbook()
    ws = wb.active
    ws.append(["user_id", "track_1", "track_2", "persona"])
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def _mock_recommender_engine() -> MagicMock:
    """Build a RecommendationEngine double that returns one stub rec."""
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    item = DiscoveredContent(
        title="示例文章",
        content_id="stub-1",
        content_url="https://example.com/1",
        source_platform="juejin",
        body_text="stub body — 长于十个字符",
        content_type="note",
        view_count=1234, like_count=56, comment_count=7,
        source_rank=1,
    )
    fake_rec = Recommendation(
        content=item, expression="ignored", topic_label="ignored",
        confidence=0.85, presented=False,
    )
    eng = MagicMock()
    eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
    return eng


def _run_cli_minimal(xlsx: Path, out_dir: Path, *extra: str) -> int:
    """Invoke ``cli.main`` with v3-hotlist source and a mocked engine.

    Used by every test that wants to demonstrate a real CLI run. The
    conftest fixtures stub candidate fetching, keyword extraction, and
    summary generation; this helper layers a per-test engine mock.
    """
    with patch.object(recommender, "build_recommender") as mock_factory:
        mock_factory.return_value = _mock_recommender_engine()
        return cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "v3-hotlist",
            "--max-parallel", "1",
            *extra,
        ])


# ---------------------------------------------------------------------------
# §"Quick start" — minimal one-user pipeline run.
# ---------------------------------------------------------------------------


def test_how_to_run_minimal_one_user_pipeline(tmp_path: Path, monkeypatch) -> None:
    """README §Quick start: run the CLI with one user and one source.

    Documented command::

        python -m heated_topics_v3.openbiliclaw_integration.cli \\
            --users-excel users.xlsx \\
            --output-dir recs/ \\
            --source v3-hotlist \\
            --max-parallel 1

    This test runs the same invocation with mocks so an agent can see
    what the CLI does and what files it produces without needing a real
    LLM API key, Ollama, or network access.
    """
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = _write_xlsx(tmp_path / "users.xlsx", [["u_001", "AI", "副业", "博主"]])
    out_dir = tmp_path / "recs"

    code = _run_cli_minimal(xlsx, out_dir)
    assert code == 0, f"CLI exited with {code}; expected 0 (all users ok)."

    # §"Output layout" — every run writes inputs/users.json + per-user dir.
    registry = json.loads(
        (out_dir / "inputs" / "users.json").read_text(encoding="utf-8")
    )
    assert "u_001" in registry, "inputs/users.json missing the user."

    user_dir = out_dir / "outputs" / "u_001"
    assert (user_dir / "input.json").exists(), "input.json was not written."
    assert (user_dir / "summary.txt").exists(), "summary.txt was not written."
    assert (user_dir / "text" / "01.txt").exists(), "text/01.txt was not written."

    payload = json.loads((user_dir / "input.json").read_text(encoding="utf-8"))
    assert payload["user_id"] == "u_001"
    assert payload["track_1"] == "AI"
    assert payload["recommendation_count"] == 1
    assert payload["articles"][0]["body_file"] == "text/01.txt"


# ---------------------------------------------------------------------------
# §"users.xlsx 格式" — header aliases (English + Chinese) and validation.
# ---------------------------------------------------------------------------


def test_how_to_validate_excel_input_with_chinese_aliases(tmp_path: Path) -> None:
    """README §"users.xlsx 格式": Chinese column aliases are accepted.

    Documented behavior: the loader accepts ``用户ID / 用户编号``,
    ``第一赛道 / 赛道一``, ``第二赛道 / 赛道二``, ``人设 / 画像`` in
    addition to the canonical English names. This test demonstrates how
    a workbook authored in Chinese is loaded.
    """
    xlsx = tmp_path / "users_cn.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["用户ID", "第一赛道", "第二赛道", "人设"])
    ws.append(["u_cn_01", "美妆护肤", "生活方式", "25-30 岁女性 KOC"])
    wb.save(xlsx)

    specs = excel_loader.load_excel(xlsx)
    assert len(specs) == 1, "Loader skipped the Chinese-header row."
    spec = specs[0]
    assert spec.user_id == "u_cn_01"
    assert spec.track_1 == "美妆护肤"
    assert spec.track_2 == "生活方式"
    assert spec.persona == "25-30 岁女性 KOC"


def test_how_to_validate_excel_input_rejects_missing_columns(
    tmp_path: Path,
) -> None:
    """README §Troubleshooting: missing required columns → ValueError.

    Documented behavior: the loader raises ``ValueError`` listing the
    missing columns before any user is processed. The CLI converts that
    to exit code 2.
    """
    xlsx = tmp_path / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["user_id", "track_1"])  # track_2 + persona missing
    ws.append(["u_x", "AI"])
    wb.save(xlsx)

    with pytest.raises(ValueError, match="missing required columns"):
        excel_loader.load_excel(xlsx)


# ---------------------------------------------------------------------------
# §"Stable user IDs" — cross-run deterministic IDs.
# ---------------------------------------------------------------------------


def test_how_to_use_stable_user_ids_across_runs() -> None:
    """README §"stable user ID": same spec → same id, change → new id.

    Documented formula::

        u_<sha256(track_1 + "\\0" + track_2 + "\\0" + persona)[:8]>

    Two specs with identical content map to the same id; editing any
    field shifts the id. The 8-hex truncation gives ~4.29B space —
    collision-free at any realistic scale.
    """
    spec_a = user_profile.UserSpec(
        user_id="excel-given-name-1",
        track_1="AI 大模型", track_2="副业", persona="技术博主",
    )
    spec_a_again = user_profile.UserSpec(
        user_id="different-excel-name",
        track_1="AI 大模型", track_2="副业", persona="技术博主",
    )
    spec_b = user_profile.UserSpec(
        user_id="excel-given-name-2",
        track_1="AI 大模型", track_2="副业", persona="改了一字",
    )

    id_a = user_profile.user_id_for_spec(spec_a)
    id_a_again = user_profile.user_id_for_spec(spec_a_again)
    id_b = user_profile.user_id_for_spec(spec_b)

    assert id_a == id_a_again, (
        "Stable id should not depend on the caller-supplied user_id field."
    )
    assert id_a != id_b, (
        "Editing any spec field must produce a new id; otherwise re-runs "
        "would silently merge distinct users."
    )
    assert id_a.startswith("u_") and len(id_a) == len("u_") + 8, (
        f"Expected u_<8hex>, got {id_a!r}"
    )


# ---------------------------------------------------------------------------
# §"Output layout" — read what the CLI wrote.
# ---------------------------------------------------------------------------


def test_how_to_read_per_user_output(tmp_path: Path, monkeypatch) -> None:
    """README §"Output layout": read input.json, summary.txt, text/NN.txt.

    This test demonstrates the consumer-side flow: after a CLI run, a
    downstream script can pick up ``outputs/<user_id>/`` without any
    special parsing — JSON for metadata, plain text for the summary
    brief, one file per article body keyed by rank.
    """
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = _write_xlsx(tmp_path / "users.xlsx", [["u_demo", "AI", "副业", "博主"]])
    out_dir = tmp_path / "recs"

    code = _run_cli_minimal(xlsx, out_dir)
    assert code == 0

    user_dir = out_dir / "outputs" / "u_demo"

    # 1) input.json: user metadata + articles index (no body, no reason).
    payload = json.loads((user_dir / "input.json").read_text(encoding="utf-8"))
    assert payload["recommendation_count"] == 1
    article0 = payload["articles"][0]
    assert article0["body_file"] == "text/01.txt"
    assert "body_text" not in article0, (
        "input.json must not duplicate bodies — readers should open text/NN.txt."
    )
    assert "reason" not in article0 and "confidence" not in article0

    # 2) text/01.txt: the body is read from this file, keyed by rank.
    body = (user_dir / "text" / "01.txt").read_text(encoding="utf-8")
    assert body == "stub body — 长于十个字符"

    # 3) summary.txt: stubbed but non-empty; file always exists so
    # downstream consumers do not have to special-case missing.
    assert (user_dir / "summary.txt").exists()
    assert (user_dir / "summary.txt").read_text(encoding="utf-8") != ""


# ---------------------------------------------------------------------------
# §"--no-keyword-extraction" — bypass LLM extraction, use track_1/track_2.
# ---------------------------------------------------------------------------


def test_how_to_disable_keyword_extraction(tmp_path: Path, monkeypatch) -> None:
    """README §"--no-keyword-extraction": no LLM call, no cache file.

    Documented behavior: with this flag the CLI uses ``track_1`` and
    ``track_2`` directly as query terms; the keyword extractor is not
    called and no cache file is written under ``_keyword_cache/``.
    """
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = _write_xlsx(tmp_path / "users.xlsx", [["u_off", "AI", "副业", "博主"]])
    out_dir = tmp_path / "recs"

    def should_not_call(*args, **kwargs):
        raise AssertionError(
            "extract_or_load must not be called when "
            "--no-keyword-extraction is set"
        )

    with patch.object(recommender, "extract_or_load", side_effect=should_not_call):
        code = _run_cli_minimal(xlsx, out_dir, "--no-keyword-extraction")

    assert code == 0
    cache = out_dir / "_keyword_cache" / "u_off" / "keyword_cache.json"
    assert not cache.exists(), (
        "With --no-keyword-extraction no keyword cache file should be written."
    )


# ---------------------------------------------------------------------------
# §"--source both" — combine V3 + last30days, write inputs/users.json.
# ---------------------------------------------------------------------------


def test_how_to_combine_v3_and_last30days_sources(
    tmp_path: Path, monkeypatch,
) -> None:
    """README §"both" source mode + §"inputs/users.json" registry.

    Documented behavior: ``--source both`` requires ``--last30days-cli-path``;
    the CLI writes one ``inputs/users.json`` for the whole run so a re-run
    with identical Excel produces a byte-identical registry.
    """
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    xlsx = _write_xlsx(
        tmp_path / "users.xlsx",
        [["u_a", "AI", "副业", "博主"], ["u_b", "美妆", "生活", "KOC"]],
    )
    out_dir = tmp_path / "recs"

    async def _fake_both(*_args, **_kwargs):
        return [{
            "article_id": "stub-1", "title": "示例文章",
            "url": "https://example.com/1",
            "body_text": "stub body — 长于十个字符",
            "author": "stub", "heat": {"rank": 1}, "tags": [],
            "platform": "weibo",
        }]

    with (
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            new=_fake_both,
        ),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        mock_factory.return_value = _mock_recommender_engine()
        code = cli.main([
            "--users-excel", str(xlsx),
            "--output-dir", str(out_dir),
            "--source", "both",
            "--last30days-cli-path", "/fake/last30days.py",
            "--max-parallel", "1",
            "--per-user-timeout", "30",
        ])

    assert code == 0

    registry = json.loads(
        (out_dir / "inputs" / "users.json").read_text(encoding="utf-8")
    )
    assert set(registry.keys()) == {"u_a", "u_b"}, (
        "inputs/users.json should map every Excel user_id to its profile."
    )
    assert registry["u_a"]["track_1"] == "AI"
    assert registry["u_b"]["persona"] == "KOC"

    # Re-running with the same Excel produces a byte-identical registry.
    registry_path = out_dir / "inputs" / "users.json"
    first_bytes = registry_path.read_bytes()
    specs = excel_loader.load_excel(xlsx)
    report_writer.write_inputs_registry(out_dir, specs)
    assert registry_path.read_bytes() == first_bytes, (
        "inputs/users.json must be deterministic across re-runs."
    )