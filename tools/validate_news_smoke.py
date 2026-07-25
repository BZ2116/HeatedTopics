from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


SECRET = re.compile(
    r"(?i)[\"']?(authorization|cookie|api[_-]?key|token|secret)[\"']?\s*[:=]\s*"
    r"(?!null\b|none\b|false\b|true\b|0\b)[\"']?[^\"'\s,}]{8,}"
)

MAX_ZHIHU_HOT_ANSWERS = 5


def _check_zhihu_hot_details(payload: dict, path: Path, violations: list[str]) -> None:
    metadata = dict(payload.get("metadata") or {})
    question = dict(metadata.get("question") or {})
    answers = list(metadata.get("answers") or [])
    if not question.get("question_id"):
        violations.append(f"zhihu-question:{path}")
    if len(answers) > MAX_ZHIHU_HOT_ANSWERS:
        violations.append(f"zhihu-answer-limit:{path}")
    for answer in answers:
        if not answer.get("answer_id") or not answer.get("url"):
            violations.append(f"zhihu-answer:{path}")


def _check_zhihu_hot_eligible(
    rows: list, path: Path, violations: list[str]
) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        hot_item = row.get("hot_item") or {}
        detail = row.get("detail") or {}
        if (hot_item.get("rank") or 0) <= 0:
            violations.append(f"zhihu-rank:{path}:{hot_item.get('item_id')}")
        metrics = dict((hot_item.get("heat") or {}).get("metrics") or {})
        if not any(float(v) > 0 for v in metrics.values()):
            violations.append(f"zhihu-metric:{path}:{hot_item.get('item_id')}")
        if not (hot_item.get("raw_payload") or {}).get("question_id"):
            violations.append(f"zhihu-question-id:{path}:{hot_item.get('item_id')}")
        if detail.get("content_status") != "full_text":
            violations.append(f"zhihu-content:{path}:{hot_item.get('item_id')}")


def _check_zhihu_daily_eligible(
    rows: list, path: Path, violations: list[str]
) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        hot_item = row.get("hot_item") or {}
        detail = row.get("detail") or {}
        if detail.get("content_status") != "full_text":
            violations.append(f"zhihu-daily-content:{path}:{hot_item.get('item_id')}")
        payload = dict(hot_item.get("raw_payload") or {})
        section = payload.get("recommendation_section")
        if section not in {"top", "latest"} and not payload.get("official_recommendation"):
            violations.append(f"zhihu-daily-section:{path}:{hot_item.get('item_id')}")


def main(root_text: str) -> int:
    root = Path(root_text)
    violations: list[str] = []
    rejected_ids: set[str] = set()
    eligible_ids: set[str] = set()

    for path in root.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        if SECRET.search(text):
            violations.append(f"credential:{path}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            violations.append(f"json:{path}")
            continue
        if "/rejected/" in path.as_posix():
            rejected_ids.update(
                str(row.get("item_id"))
                for row in payload
                if isinstance(row, dict) and row.get("item_id")
            )
        if "/eligible/" in path.as_posix():
            eligible_ids.update(
                str(row.get("hot_item", {}).get("item_id"))
                for row in payload
                if isinstance(row, dict)
            )
        if path.name.startswith("zhihu_hot_") and "/details/" in path.as_posix():
            if isinstance(payload, dict):
                _check_zhihu_hot_details(payload, path, violations)
            continue
        if path.name == "zhihu_hot.json" and "/eligible/" in path.as_posix():
            if isinstance(payload, list):
                _check_zhihu_hot_eligible(payload, path, violations)
            continue
        if path.name == "zhihu_daily.json" and "/eligible/" in path.as_posix():
            if isinstance(payload, list):
                _check_zhihu_daily_eligible(payload, path, violations)
            continue
        if path.name != "result.json":
            continue
        by_platform: dict[str, list[float]] = defaultdict(list)
        for row in payload.get("recommendations", []):
            if row.get("content_status") != "full_text" or not row.get("detail"):
                violations.append(f"content:{path}:{row.get('hot_item_id')}")
            evidence = row.get("evidence", {})
            qualified_by = tuple(evidence.get("qualified_by") or ())
            metrics = dict(evidence.get("metrics") or {})
            if not qualified_by:
                violations.append(f"evidence:{path}:{row.get('hot_item_id')}")
            elif evidence.get("source_kind") == "official_hot_board":
                rank = evidence.get("platform_rank") or 0
                native = evidence.get("native_hot_value") or 0
                if rank <= 0 and native <= 0 and not any(v > 0 for v in metrics.values()):
                    violations.append(f"evidence:{path}:{row.get('hot_item_id')}")
            elif not any(v > 0 for v in metrics.values()):
                violations.append(f"evidence:{path}:{row.get('hot_item_id')}")
            by_platform[str(row.get("platform"))].append(
                float(evidence.get("platform_heat_score", 0.0))
            )
        for platform, scores in by_platform.items():
            if len(scores) > 20:
                violations.append(f"limit:{path}:{platform}")
            if scores != sorted(scores, reverse=True):
                violations.append(f"order:{path}:{platform}")

    overlap = rejected_ids.intersection(eligible_ids)
    if overlap:
        violations.append(f"rejected-eligible-overlap:{sorted(overlap)}")
    if violations:
        print(json.dumps({"status": "failed", "violations": violations},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"status": "success", "violations": []},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
