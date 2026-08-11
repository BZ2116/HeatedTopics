"""Tests for Excel input loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from heated_topics_v3.openbiliclaw_integration import excel_loader
from heated_topics_v3.openbiliclaw_integration.user_profile import (
    ProfileValidationError,
    UserSpec,
)


def _write_xlsx(
    path: Path,
    rows: list[list[str]],
    header: list[str] | None = None,
) -> None:
    wb = Workbook()
    ws = wb.active
    if header:
        ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_load_excel_returns_user_specs(tmp_path: Path) -> None:
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(
        xlsx,
        rows=[
            ["u_001", "AI 大模型", "副业", "技术博主"],
            ["u_002", "美妆护肤", "生活方式", "25-30 岁女性 KOC"],
        ],
        header=["user_id", "track_1", "track_2", "persona"],
    )
    specs = excel_loader.load_excel(xlsx)
    assert len(specs) == 2
    assert isinstance(specs[0], UserSpec)
    assert specs[0].user_id == "u_001"
    assert specs[0].track_1 == "AI 大模型"
    assert specs[1].persona == "25-30 岁女性 KOC"


def test_load_excel_accepts_alternate_header_names(tmp_path: Path) -> None:
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(
        xlsx,
        rows=[["u_001", "AI", "副业", "博主"]],
        header=["用户ID", "第一赛道", "第二赛道", "人设"],
    )
    specs = excel_loader.load_excel(xlsx)
    assert specs[0].user_id == "u_001"


def test_load_excel_skips_blank_rows(tmp_path: Path) -> None:
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(
        xlsx,
        rows=[
            ["u_001", "AI", "副业", "博主"],
            ["", "", "", ""],
            ["u_002", "美妆", "生活", "KOC"],
        ],
        header=["user_id", "track_1", "track_2", "persona"],
    )
    specs = excel_loader.load_excel(xlsx)
    assert len(specs) == 2


def test_load_excel_raises_on_missing_user_id(tmp_path: Path) -> None:
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(
        xlsx,
        rows=[["", "AI", "副业", "博主"]],
        header=["user_id", "track_1", "track_2", "persona"],
    )
    with pytest.raises(ProfileValidationError):
        excel_loader.load_excel(xlsx)


def test_load_excel_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        excel_loader.load_excel(tmp_path / "nope.xlsx")


def test_load_excel_raises_on_missing_required_column(tmp_path: Path) -> None:
    xlsx = tmp_path / "users.xlsx"
    _write_xlsx(
        xlsx,
        rows=[["u_001", "AI"]],
        header=["user_id", "track_1"],
    )
    with pytest.raises(ValueError, match="track_2"):
        excel_loader.load_excel(xlsx)


def test_load_excel_raises_on_empty_workbook(tmp_path: Path) -> None:
    xlsx = tmp_path / "empty.xlsx"
    wb = Workbook()
    wb.active
    wb.save(xlsx)
    with pytest.raises(ProfileValidationError):
        excel_loader.load_excel(xlsx)