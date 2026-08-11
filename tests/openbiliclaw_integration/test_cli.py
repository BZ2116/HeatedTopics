"""Tests for v2 CLI surface."""

from __future__ import annotations

import pytest

from heated_topics_v3.openbiliclaw_integration import cli


def test_parse_args_requires_users_excel() -> None:
    args = cli.parse_args(["--users-excel", "users.xlsx", "--output-dir", "x"])
    assert args.users_excel.name == "users.xlsx"


def test_parse_args_supports_body_max_chars() -> None:
    args = cli.parse_args(
        [
            "--users-excel", "users.xlsx",
            "--output-dir", "recs/",
            "--body-max-chars", "30000",
        ]
    )
    assert args.body_max_chars == 30000


def test_parse_args_drops_v1_flags() -> None:
    """V1 flags like --use-search should not be accepted."""
    with pytest.raises(SystemExit):
        cli.parse_args(
            [
                "--users-excel", "users.xlsx",
                "--output-dir", "recs/",
                "--use-search",
            ]
        )


def test_parse_args_default_source_is_both() -> None:
    args = cli.parse_args(
        ["--users-excel", "users.xlsx", "--output-dir", "recs/"]
    )
    assert args.source == "both"


def test_parse_args_default_limit_is_15() -> None:
    args = cli.parse_args(
        ["--users-excel", "users.xlsx", "--output-dir", "recs/"]
    )
    assert args.limit == 15


def test_parse_args_keyword_extraction_defaults_to_true() -> None:
    args = cli.parse_args(
        ["--users-excel", "u.xlsx", "--output-dir", "o/"]
    )
    assert args.keyword_extraction is True


def test_parse_args_no_keyword_extraction_disables() -> None:
    args = cli.parse_args(
        [
            "--users-excel", "u.xlsx",
            "--output-dir", "o/",
            "--no-keyword-extraction",
        ]
    )
    assert args.keyword_extraction is False
