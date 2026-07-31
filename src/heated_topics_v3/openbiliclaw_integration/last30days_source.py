"""Subprocess wrapper around the last30days CLI.

Black-box invocation of ``scripts/last30days.py``. Writes the JSON the CLI
emits on stdout to ``<save_dir>/report.json`` and returns its path, so the
adapter layer can read it without coupling to subprocess details.

We use ``--emit json`` and capture stdout (last30days writes the report to
stdout in JSON mode; ``--save-dir`` is used purely as a working directory
so the relative ``--save-dir`` path the CLI needs is honoured).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from heated_topics_v3.openbiliclaw_integration.exceptions import (
    Last30DaysParseError,
    Last30DaysSourceError,
)

logger = logging.getLogger(__name__)


_REPORT_FILENAME = "report.json"


def run(
    *,
    cli_path: Path,
    query: str,
    days: int,
    save_dir: Path,
    fetch_bodies: bool,
    platforms: Sequence[str],
    timeout: float,
) -> Path:
    """Invoke last30days CLI and return the path to ``report.json``.

    Raises Last30DaysSourceError on subprocess failure or missing output.
    The output JSON is NOT parsed here — callers use ``parse_report()``.
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(cli_path),
        query,  # positional topic arg (verified against --help output)
        "--days", str(days),
        "--emit", "json",
        "--save-dir", str(save_dir),
        "--timeout", str(int(timeout)),
    ]
    if fetch_bodies:
        cmd.append("--fetch-bodies")
    if platforms:
        cmd.extend(["--search", ",".join(platforms)])

    output_path = _run_subprocess(cmd, save_dir=save_dir, timeout=timeout)

    if not output_path.exists():
        raise Last30DaysSourceError(
            f"last30days exited but {output_path} was not produced"
        )
    return output_path


def _run_subprocess(cmd: list[str], *, save_dir: Path, timeout: float) -> Path:
    """Spawn last30days subprocess, capture stdout, persist to report.json.

    Split out so tests can mock at the subprocess.run boundary.
    Returns the path where stdout was persisted.
    """
    logger.info("invoking last30days: %s", " ".join(cmd[1:]))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(save_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise Last30DaysSourceError(
            f"last30days timed out after {timeout}s"
        ) from exc

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-500:]
        raise Last30DaysSourceError(
            f"last30days exited {result.returncode}: {stderr_tail}"
        )

    out_path = save_dir / _REPORT_FILENAME
    out_path.write_text(result.stdout or "", encoding="utf-8")
    return out_path


def parse_report(report_path: Path) -> dict:
    """Parse the last30days JSON report into a dict.

    Raises Last30DaysParseError on missing file, invalid JSON, or
    non-object top level. Returns the full dict; per-platform mapping
    is the adapter's job.
    """
    try:
        raw = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Last30DaysParseError(
            f"cannot read {report_path}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Last30DaysParseError(
            f"{report_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise Last30DaysParseError(
            f"{report_path}: expected object at top level, "
            f"got {type(data).__name__}"
        )
    return data