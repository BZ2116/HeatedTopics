"""Smoke-test the validator script itself with a synthetic data root.

This test does not hit the network; it writes a throwaway tree under
``tmp_path`` that exercises every branch the validator cares about
(secret-shaped string, malformed JSON, rejected/eligible overlap,
``result.json`` content / evidence / order / limit checks) and asserts
the script returns ``1`` with the expected violation list. A clean tree
is also asserted to return ``0``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "validate_news_smoke.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_zhihu_rank_only_result_passes(tmp_path: Path) -> None:
    payload = {
        "recommendations": [
            {
                "hot_item_id": "zhihu_daily_1001",
                "platform": "zhihu_daily",
                "content_status": "full_text",
                "detail": "accepted body",
                "source_url": "https://daily.zhihu.com/story/1001",
                "evidence": {
                    "source_kind": "official_hot_board",
                    "platform_rank": 1,
                    "native_hot_value": None,
                    "metrics": {},
                    "threshold_metrics": {},
                    "qualified_by": ["official_hot_board"],
                    "platform_heat_score": 0.0,
                },
            }
        ]
    }
    (tmp_path / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "success", "violations": []}


def test_public_engagement_with_empty_metrics_still_fails(tmp_path: Path) -> None:
    payload = {
        "recommendations": [
            {
                "hot_item_id": "bad-1",
                "platform": "sina_news",
                "content_status": "full_text",
                "detail": "body",
                "evidence": {
                    "source_kind": "public_engagement",
                    "platform_rank": None,
                    "native_hot_value": None,
                    "metrics": {},
                    "qualified_by": [],
                    "platform_heat_score": 0.0,
                },
            }
        ]
    }
    (tmp_path / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    violations = json.loads(result.stdout)["violations"]
    assert any(v.startswith("evidence:") for v in violations)


def test_clean_tree_returns_success(tmp_path: Path) -> None:
    (tmp_path / "empty.json").write_text("[]", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"status": "success", "violations": []}


def test_detects_credentials_and_overlap_and_result_violations(tmp_path: Path) -> None:
    # Credential-shaped string in a raw file. The validator only walks
    # ``*.json`` files, so the credential must be embedded inside a JSON
    # file (not a sidecar header). The plan's SECRET regex matches the
    # header form (``Cookie: abcd12345678``) when it appears as a substring
    # of any JSON file's text.
    (tmp_path / "raw").mkdir(parents=True)
    (tmp_path / "raw" / "headers.json").write_text(
        '"request":{"Cookie: abcd12345678"}', encoding="utf-8"
    )

    # Overlap between eligible and rejected.
    (tmp_path / "eligible").mkdir(parents=True)
    (tmp_path / "rejected").mkdir(parents=True)
    (tmp_path / "eligible" / "sina.json").write_text(
        json.dumps([{"hot_item": {"item_id": "shared"}}]), encoding="utf-8"
    )
    (tmp_path / "rejected" / "sina.json").write_text(
        json.dumps([{"item_id": "shared"}]), encoding="utf-8"
    )

    # result.json that violates content / evidence / order / limit.
    result_payload = {
        "recommendations": [
            {
                "hot_item_id": "ok-1",
                "platform": "sina_news",
                "content_status": "title_only",
                "detail": "body",
                "evidence": {"qualified_by": ("top_num",), "metrics": {"top_num": 1.0}, "platform_heat_score": 2.0},
            },
            {
                "hot_item_id": "ok-2",
                "platform": "sina_news",
                "content_status": "full_text",
                "detail": "body",
                "evidence": {"qualified_by": (), "metrics": {}, "platform_heat_score": 1.0},
            },
            {
                "hot_item_id": "ok-3",
                "platform": "sina_news",
                "content_status": "full_text",
                "detail": "body",
                "evidence": {"qualified_by": ("top_num",), "metrics": {"top_num": 1.0}, "platform_heat_score": 3.0},
            },
            {
                "hot_item_id": "ok-4",
                "platform": "sina_news",
                "content_status": "full_text",
                "detail": "body",
                "evidence": {"qualified_by": ("top_num",), "metrics": {"top_num": 1.0}, "platform_heat_score": 2.0},
            },
        ]
    }
    result_payload["recommendations"].extend(
        {
            "hot_item_id": f"extra-{i}",
            "platform": "sina_news",
            "content_status": "full_text",
            "detail": "body",
            "evidence": {
                "qualified_by": ("top_num",),
                "metrics": {"top_num": 1.0},
                "platform_heat_score": float(i),
            },
        }
        for i in range(5, 25)
    )
    (tmp_path / "result.json").write_text(
        json.dumps(result_payload), encoding="utf-8"
    )

    # Malformed JSON file.
    (tmp_path / "bad.json").write_text("{not-json", encoding="utf-8")

    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    violations = payload["violations"]
    joined = "\n".join(violations)
    assert any(v.startswith("credential:") for v in violations)
    assert any(v.startswith("rejected-eligible-overlap:") for v in violations)
    assert any(v.startswith("content:") for v in violations)
    assert any(v.startswith("evidence:") for v in violations)
    assert any(v.startswith("order:") for v in violations)
    assert any(v.startswith("limit:") for v in violations)
    assert any(v.startswith("json:") for v in violations)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
