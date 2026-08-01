"""Read user profiles from an Excel workbook (.xlsx).

Schema: 4 columns — user_id, track_1, track_2, persona.
Header row may use either English (case-insensitive) or Chinese names;
matches by content, not strict ordering. Blank rows are skipped.
Validation errors raise ProfileValidationError.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from heated_topics_v3.openbiliclaw_integration.user_profile import (
    ProfileValidationError,
    UserSpec,
    load_users,
)


# Map known header aliases to canonical names. Case-insensitive, trimmed.
_HEADER_ALIASES: dict[str, str] = {
    "user_id": "user_id",
    "userid": "user_id",
    "id": "user_id",
    "用户id": "user_id",
    "用户编号": "user_id",
    "track_1": "track_1",
    "track1": "track_1",
    "first_track": "track_1",
    "第一赛道": "track_1",
    "赛道一": "track_1",
    "track_2": "track_2",
    "track2": "track_2",
    "second_track": "track_2",
    "第二赛道": "track_2",
    "赛道二": "track_2",
    "persona": "persona",
    "人设": "persona",
    "画像": "persona",
}


_REQUIRED_COLS: tuple[str, ...] = ("user_id", "track_1", "track_2", "persona")


def _canonicalize_header(name: str) -> str | None:
    return _HEADER_ALIASES.get(name.strip().lower())


def load_excel(path: Path) -> list[UserSpec]:
    """Load users from an .xlsx file. Returns validated UserSpec list."""
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if header_row is None:
            raise ProfileValidationError(f"{path}: empty workbook")
        canonical = [_canonicalize_header(str(c or "")) for c in header_row]
        missing = [c for c in _REQUIRED_COLS if c not in canonical]
        if missing:
            raise ValueError(
                f"{path}: missing required columns {missing}. "
                f"Got headers {[str(c) for c in header_row]}"
            )
        idx = {name: canonical.index(name) for name in _REQUIRED_COLS}
        raw_specs: list[dict[str, str]] = []
        for row in rows_iter:
            if row is None or all(
                c is None or str(c).strip() == "" for c in row
            ):
                continue
            raw_specs.append(
                {
                    "user_id": str(row[idx["user_id"]] or "").strip(),
                    "track_1": str(row[idx["track_1"]] or "").strip(),
                    "track_2": str(row[idx["track_2"]] or "").strip(),
                    "persona": str(row[idx["persona"]] or "").strip(),
                }
            )
        return load_users(raw_specs)
    finally:
        wb.close()