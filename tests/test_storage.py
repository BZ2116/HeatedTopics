import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from heated_topics_v3.contracts import (
    DailySnapshot,
    HeatMetrics,
    HotItem,
    PlatformCollectionStatus,
    RecommendationBundle,
    RecommendationItem,
)
from heated_topics_v3.storage import FileRepository


def hot_item(**changes):
    item = HotItem(
        item_id="百度-1",
        platform="baidu",
        title="人工智能热点",
        url="https://example.test/1",
        rank=1,
        heat=HeatMetrics(value=123, label="123万", metric_name="热度", metrics={"views": 123}),
        summary="摘要",
        publication_time=None,
        collected_at="2026-07-13T08:01:00+08:00",
        raw_payload={"nested": {"cookie": "bad", "safe": "保留"}, "Authorization": "Bearer bad"},
    )
    return replace(item, **changes)


def recommendation(**changes):
    item = RecommendationItem(
        hot_item_id="百度-1",
        platform="baidu",
        title="人工智能热点",
        heat_level=3,
        fact_status="verified",
        publication_time=None,
        collected_at="2026-07-13T08:01:00+08:00",
        detail="详情",
        content_status="summary",
        is_personalized=True,
        evidence={"safe": True},
        source_url="https://example.test/1",
    )
    return replace(item, **changes)


def bundle(day="2026-07-13"):
    return RecommendationBundle(
        status="generated",
        user_id="user_001",
        business_date=day,
        generated_at=f"{day}T08:02:00+08:00",
        recommendations=(recommendation(),),
        potential_topics=(),
        general_fallback=(),
        query_metadata={"query": "人工智能"},
    )


def test_raw_files_use_exact_daily_layout(tmp_path):
    repo = FileRepository(tmp_path)

    path = repo.save_raw(date(2026, 7, 13), "baidu", "<html />", suffix="html")

    assert path == tmp_path / "daily_hot_lists/2026-07-13/raw/baidu.html"
    assert path.read_text("utf-8") == "<html />"


def test_normalized_json_is_utf8_formatted_and_recursively_sanitized(tmp_path):
    repo = FileRepository(tmp_path)

    path = repo.save_normalized(date(2026, 7, 13), "baidu", (hot_item(),))
    text = path.read_text("utf-8")
    data = json.loads(text)

    assert text.endswith("\n")
    assert "  \"item_id\"" in text
    assert "人工智能热点" in text
    assert data[0]["raw_payload"] == {"nested": {"safe": "保留"}}
    lowered = text.lower()
    assert all(field not in lowered for field in ("cookie", "api_key", "secret", "authorization"))


def test_normalized_json_removes_secret_key_aliases_but_preserves_harmless_values(tmp_path):
    repo = FileRepository(tmp_path)
    payload = {
        "x-api-key": "bad-1",
        "apiKey": "bad-2",
        "nested": {
            "apikey": "bad-3",
            "Authorization": "Bearer bad",
            "Cookie": "session=bad",
            "QIANFAN_SECRET_KEY": "bad-4",
            "description": "Cookie, apikey, Authorization, and QIANFAN_SECRET_KEY are words here",
        },
    }

    path = repo.save_normalized(
        date(2026, 7, 13), "baidu", (hot_item(raw_payload=payload),)
    )

    assert json.loads(path.read_text("utf-8"))[0]["raw_payload"] == {
        "nested": {
            "description": "Cookie, apikey, Authorization, and QIANFAN_SECRET_KEY are words here"
        }
    }


def test_snapshot_round_trips_as_contracts(tmp_path):
    repo = FileRepository(tmp_path)
    day = date(2026, 7, 13)
    repo.save_normalized(day, "baidu", (hot_item(),))
    repo.save_collection_status(
        day,
        (
            PlatformCollectionStatus(
                platform="baidu",
                status="success",
                collected_at="2026-07-13T08:01:00+08:00",
                item_count=1,
            ),
        ),
    )

    loaded = repo.load_daily_snapshot(day)

    assert isinstance(loaded, DailySnapshot)
    assert loaded.business_date == "2026-07-13"
    assert loaded.items_by_platform["baidu"] == (hot_item(raw_payload={"nested": {"safe": "保留"}}),)
    assert loaded.platform_statuses[0].status == "success"


def test_detail_uses_common_detail_path(tmp_path):
    repo = FileRepository(tmp_path)
    path = repo.save_detail(date(2026, 7, 13), "baidu", 2, "中文详情")
    assert path == tmp_path / "daily_hot_lists/2026-07-13/details/baidu_2.txt"
    assert path.read_text("utf-8") == "中文详情"


def test_atomic_result_round_trips_and_existing_result_is_not_overwritten(tmp_path):
    repo = FileRepository(tmp_path)

    first = repo.write_user_result_atomic("user_001", "2026-07-13", lambda directory: repo.write_json(directory / "result.json", bundle()))
    second = repo.write_user_result_atomic("user_001", "2026-07-13", lambda directory: (_ for _ in ()).throw(AssertionError("called")))

    assert first == tmp_path / "user_results/user_001/2026-07-13"
    assert second == first
    assert repo.load_user_bundle("user_001", "2026-07-13") == bundle()


def test_latest_user_bundle_uses_latest_business_date(tmp_path):
    repo = FileRepository(tmp_path)
    for day in ("2026-07-12", "2026-07-13"):
        repo.write_user_result_atomic("user_001", day, lambda directory, value=bundle(day): repo.write_json(directory / "result.json", value))

    assert repo.load_latest_user_bundle("user_001") == bundle("2026-07-13")
    assert repo.load_user_bundle("missing", "2026-07-13") is None


def test_atomic_result_failure_leaves_no_final_or_temporary_directory(tmp_path):
    repo = FileRepository(tmp_path)

    def fail(directory):
        (directory / "partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("generation failed")

    with pytest.raises(RuntimeError, match="generation failed"):
        repo.write_user_result_atomic("user_001", "2026-07-13", fail)

    parent = tmp_path / "user_results/user_001"
    assert not (parent / "2026-07-13").exists()
    assert not list(parent.glob("2026-07-13.tmp-*"))


def test_atomic_publish_accepts_oserror_only_when_another_complete_directory_wins(
    tmp_path, monkeypatch
):
    repo = FileRepository(tmp_path)
    original_replace = Path.replace

    def concurrent_publish(path, target):
        target.mkdir(parents=True)
        (target / "result.json").write_text("{}", encoding="utf-8")
        raise OSError("simulated Windows directory publish race")

    monkeypatch.setattr(Path, "replace", concurrent_publish)
    final = repo.write_user_result_atomic(
        "user_001",
        "2026-07-13",
        lambda directory: repo.write_json(directory / "result.json", bundle()),
    )
    monkeypatch.setattr(Path, "replace", original_replace)

    assert final == tmp_path / "user_results/user_001/2026-07-13"
    assert not list(final.parent.glob("2026-07-13.tmp-*"))
