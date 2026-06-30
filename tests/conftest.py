"""Pytest configuration: prevent test pollution of project data/ and reports/.

`run_recent_detail_collection` defaults to `root=Path(".")`. When tests run from
the project root and forget to pass an explicit `root=tmp_path`, they overwrite
real data/raw, data/evidence, data/processed, and reports files. This guard
snapshots the project data state at session start and asserts it stays unchanged
across the whole test session.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GUARDED_PATHS = (
    _PROJECT_ROOT / "data" / "raw" / "dailyhot_records.json",
    _PROJECT_ROOT / "data" / "evidence" / "detail_evidence.json",
    _PROJECT_ROOT / "data" / "evidence" / "detail_evidence_raw.jsonl",
    _PROJECT_ROOT / "data" / "processed" / "topic_clusters.json",
    _PROJECT_ROOT / "data" / "processed" / "creator_topic_index.json",
    _PROJECT_ROOT / "reports" / "creator_topic_cards.md",
    _PROJECT_ROOT / "reports" / "recent_hot_topics_digest.md",
)


def _snapshot() -> dict[Path, tuple[float, int] | None]:
    snapshot: dict[Path, tuple[float, int] | None] = {}
    for path in _GUARDED_PATHS:
        if path.exists():
            stat = path.stat()
            snapshot[path] = (stat.st_mtime, stat.st_size)
        else:
            snapshot[path] = None
    return snapshot


@pytest.fixture(scope="session", autouse=True)
def _guard_project_data_dir():
    before = _snapshot()
    yield
    after = _snapshot()
    offenders: list[str] = []
    for path in _GUARDED_PATHS:
        before_state = before[path]
        after_state = after[path]
        if before_state != after_state:
            offenders.append(f"{path.relative_to(_PROJECT_ROOT)}: {before_state} -> {after_state}")
    if offenders:
        raise AssertionError(
            "Tests must not modify project data/ or reports/ files. "
            "Pass root=tmp_path (or a tmp_path fixture) to run_recent_detail_collection. "
            "Polluting files:\n  - " + "\n  - ".join(offenders)
        )
