"""Tests for the single-summary per-user report layout."""
from __future__ import annotations

import json
from pathlib import Path

from heated_topics_v3.openbiliclaw_integration.report_writer import (
    write_inputs_registry,
    write_user_report,
)
from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec


def _mk_item(
    *,
    rank: int,
    content_id: str = "r",
    title: str = "t",
    body: str = "body",
    url: str = "https://x.com/a",
    platform: str = "weibo",
    search_query: str = "",
) -> dict:
    return {
        "rank": rank,
        "title": title,
        "url": url,
        "source": platform,
        "search_query": search_query,
        "heat": {
            "view": 100, "like": 10, "comment": 0,
            "favorite": 0, "share": 0, "rank": 1,
        },
        "body_text": body,
        "body_text_length": len(body),
        "body_truncated": False,
        "published_at": "2026-08-01",
        "content_id": content_id,
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_write_user_report_creates_single_summary_and_text_dir(tmp_path: Path) -> None:
    write_user_report(
        tmp_path / "u_test",
        user_id="u_test",
        track_1="美食",
        track_2="探店",
        persona="博主",
        recommendations=[_mk_item(rank=1, title="火锅", body="完整正文", search_query="夏日美食")],
        summary="整体覆盖夏日美食与探店内容。",
    )
    base = tmp_path / "u_test"
    assert (base / "input.json").exists()
    assert (base / "summary.txt").read_text(encoding="utf-8") == "整体覆盖夏日美食与探店内容。"
    assert (base / "text" / "01.txt").read_text(encoding="utf-8") == "完整正文"
    assert not (base / "queries").exists()
    assert not (base / "summaries").exists()


def test_input_json_contains_article_index_without_body(tmp_path: Path) -> None:
    item = _mk_item(
        rank=1, content_id="r1", title="火锅", platform="weibo",
        search_query="夏日美食",
    )
    write_user_report(
        tmp_path / "u",
        user_id="u_demo", track_1="美食", track_2="探店", persona="博主A",
        recommendations=[item], summary="摘要",
    )
    payload = _read_json(tmp_path / "u" / "input.json")
    assert payload["user_id"] == "u_demo"
    assert payload["recommendation_count"] == 1
    assert payload["summary_file"] == "summary.txt"
    assert payload["articles"] == [{
        "rank": 1,
        "title": "火锅",
        "url": "https://x.com/a",
        "platform": "weibo",
        "query": "夏日美食",
        "heat": {
            "view": 100, "like": 10, "comment": 0,
            "favorite": 0, "share": 0, "rank": 1,
        },
        "published_at": "2026-08-01",
        "body_file": "text/01.txt",
    }]
    assert "body_text" not in payload["articles"][0]


def test_text_files_are_rank_padded_and_truncated(tmp_path: Path) -> None:
    items = [
        _mk_item(rank=i, content_id=f"r{i}", body=f"body-{i}", search_query="Q")
        for i in range(1, 11)
    ]
    items[0]["body_text"] = "x" * 500
    write_user_report(
        tmp_path / "u", user_id="u", track_1="x", track_2="y", persona="z",
        recommendations=items, summary="", body_max_chars=100,
    )
    text_dir = tmp_path / "u" / "text"
    assert sorted(p.name for p in text_dir.iterdir()) == [f"{i:02d}.txt" for i in range(1, 11)]
    assert len((text_dir / "01.txt").read_text(encoding="utf-8")) == 100
    assert (text_dir / "10.txt").read_text(encoding="utf-8") == "body-10"


def test_empty_summary_still_creates_summary_file(tmp_path: Path) -> None:
    write_user_report(
        tmp_path / "u", user_id="u", track_1="x", track_2="y", persona="z",
        recommendations=[], summary=None,
    )
    assert (tmp_path / "u" / "summary.txt").read_text(encoding="utf-8") == ""


def test_write_inputs_registry_round_trips_specs(tmp_path: Path) -> None:
    specs = [
        UserSpec("u1", track_1="美食", track_2="探店", persona="博主A"),
        UserSpec("u2", track_1="知识", track_2="学习", persona="学生"),
    ]
    write_inputs_registry(tmp_path, specs)
    registry = _read_json(tmp_path / "inputs" / "users.json")
    assert registry == {
        "u1": {"track_1": "美食", "track_2": "探店", "persona": "博主A"},
        "u2": {"track_1": "知识", "track_2": "学习", "persona": "学生"},
    }


def test_inputs_registry_is_byte_identical_across_runs(tmp_path: Path) -> None:
    specs = [UserSpec("u", track_1="A", track_2="B", persona="P")]
    write_inputs_registry(tmp_path, specs)
    first = (tmp_path / "inputs" / "users.json").read_bytes()
    write_inputs_registry(tmp_path, specs)
    assert first == (tmp_path / "inputs" / "users.json").read_bytes()
