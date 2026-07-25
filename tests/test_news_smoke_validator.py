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


def test_smoke_validator_rejects_more_than_five_zhihu_answers(tmp_path: Path):
    details = tmp_path / "daily_hot_lists" / "2026-07-25" / "details"
    details.mkdir(parents=True)
    (details / "zhihu_hot_zhihu_hot_question_1.json").write_text(
        json.dumps({
            "item_id": "zhihu_hot_question_1",
            "content": "合格问题正文。",
            "content_status": "full_text",
            "publication_time": None,
            "collected_at": "2026-07-25T12:00:00+08:00",
            "source_url": "https://www.zhihu.com/question/1",
            "fetch_status": "success",
            "metadata": {
                "question": {"question_id": "1", "view_count": 100},
                "answers": [
                    {
                        "answer_id": str(index),
                        "url": f"https://www.zhihu.com/question/1/answer/{index}",
                    }
                    for index in range(6)
                ],
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert any(
        violation.startswith("zhihu-answer-limit:")
        for violation in json.loads(result.stdout)["violations"]
    )


def test_smoke_validator_accepts_ranked_zhihu_hot_and_daily(tmp_path: Path):
    eligible = tmp_path / "daily_hot_lists" / "2026-07-25" / "eligible"
    details = tmp_path / "daily_hot_lists" / "2026-07-25" / "details"
    eligible.mkdir(parents=True)
    details.mkdir(parents=True)
    hot_detail = {
        "item_id": "zhihu_hot_question_1",
        "content": "第一段完整问题内容。\n\n第二段完整热门回答内容。",
        "content_status": "full_text",
        "publication_time": None,
        "collected_at": "2026-07-25T12:00:00+08:00",
        "source_url": "https://www.zhihu.com/question/1",
        "fetch_status": "success",
        "metadata": {
            "question": {"question_id": "1", "view_count": 100},
            "answers": [{
                "answer_id": "11",
                "url": "https://www.zhihu.com/question/1/answer/11",
            }],
        },
    }
    hot_article = {
        "hot_item": {
            "item_id": "zhihu_hot_question_1",
            "platform": "zhihu_hot",
            "title": "示例热榜问题",
            "url": "https://www.zhihu.com/question/1",
            "rank": 1,
            "heat": {
                "value": 1000,
                "label": "1000 热度",
                "metric_name": "hot_score",
                "metrics": {"hot_score": 1000},
            },
            "summary": "摘要",
            "publication_time": None,
            "collected_at": "2026-07-25T12:00:00+08:00",
            "raw_payload": {"question_id": "1"},
        },
        "detail": hot_detail,
        "heat_evidence": {
            "source_kind": "official_hot_board",
            "platform_rank": 1,
            "native_hot_value": 1000,
            "metrics": {"hot_score": 1000},
            "threshold_metrics": {"hot_score": 1},
            "qualified_by": ["official_hot_board"],
        },
        "content_validation": {
            "status": "accepted",
            "parser": "fixture",
            "character_count": 100,
            "paragraph_count": 2,
            "reasons": [],
        },
        "platform_heat_score": 1.0,
    }
    daily_article = json.loads(json.dumps(hot_article))
    daily_article["hot_item"].update({
        "item_id": "zhihu_daily_2",
        "platform": "zhihu_daily",
        "url": "https://daily.zhihu.com/story/2",
        "heat": {"value": None, "label": "", "metric_name": "rank", "metrics": {}},
        "raw_payload": {
            "story_id": 2,
            "recommendation_section": "latest",
            "recommendation_sections": ["latest"],
        },
    })
    daily_article["detail"].update({
        "item_id": "zhihu_daily_2",
        "source_url": "https://daily.zhihu.com/story/2",
        "metadata": {},
    })
    daily_article["heat_evidence"].update({
        "native_hot_value": None,
        "metrics": {},
        "threshold_metrics": {},
    })
    (eligible / "zhihu_hot.json").write_text(
        json.dumps([hot_article], ensure_ascii=False), encoding="utf-8"
    )
    (eligible / "zhihu_daily.json").write_text(
        json.dumps([daily_article], ensure_ascii=False), encoding="utf-8"
    )
    (details / "zhihu_hot_zhihu_hot_question_1.json").write_text(
        json.dumps(hot_detail, ensure_ascii=False), encoding="utf-8"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_smoke_validator_rejects_cookie_shaped_content(tmp_path: Path):
    path = tmp_path / "daily_hot_lists" / "2026-07-25" / "eligible" / "zhihu_hot.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[{"Cookie":"z_c0=123456789abcdef"}]',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert any(
        violation.startswith("credential:")
        for violation in json.loads(result.stdout)["violations"]
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
