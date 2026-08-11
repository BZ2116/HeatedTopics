"""Shared pytest fixtures for openbiliclaw_integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def tmp_xlsx(tmp_path: Path) -> Path:
    """Create a 2-user xlsx in tmp_path. Returns the path."""
    p = tmp_path / "users.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["user_id", "track_1", "track_2", "persona"])
    ws.append(["u_alpha", "AI 大模型", "副业", "技术博主"])
    ws.append(["u_beta", "美妆护肤", "生活方式", "KOC"])
    wb.save(p)
    return p


@pytest.fixture
def tmp_xlsx_path(tmp_path: Path) -> callable:
    """Factory: write a custom xlsx and return its path."""
    def _make(rows: list[list[str]]) -> Path:
        p = tmp_path / "users.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["user_id", "track_1", "track_2", "persona"])
        for r in rows:
            ws.append(r)
        wb.save(p)
        return p
    return _make