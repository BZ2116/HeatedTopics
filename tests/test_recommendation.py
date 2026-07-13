import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import heated_topics_v3.recommendation as recommendation_module
from heated_topics_v3.contracts import HeatMetrics, HotItem, UserProfile
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.recommendation import generate_v1_user_result
from heated_topics_v3.storage import FileRepository


NOW = datetime.fromisoformat("2026-07-13T08:05:00+08:00")
COLLECTED_AT = "2026-07-13T08:01:00+08:00"


def _profile() -> UserProfile:
    return UserProfile("u1", "AI", "应用", "职场", "AI工具", COLLECTED_AT)


def _item(
    item_id: str,
    platform: str,
    title: str,
    rank: int,
    *,
    group_id: str = "",
) -> HotItem:
    metric = "hot_value" if platform == "toutiao" else "hot_rank"
    return HotItem(
        item_id=item_id,
        platform=platform,
        title=title,
        url=f"https://example.test/{item_id}",
        rank=rank,
        heat=HeatMetrics(rank * 100, str(rank * 100), metric, {"views": rank * 10}),
        summary=f"{title} summary",
        publication_time="2026-07-13T00:00:00Z",
        collected_at=COLLECTED_AT,
        raw_payload={"ClusterIdStr": group_id} if group_id else {},
    )


def _save_daily(repository: FileRepository, toutiao=(), juejin=()) -> None:
    repository.save_normalized("2026-07-13", "toutiao", toutiao)
    repository.save_normalized("2026-07-13", "juejin", juejin)
    for platform, items in (("toutiao", toutiao), ("juejin", juejin)):
        for sequence, item in enumerate(items, 1):
            repository.save_detail(
                "2026-07-13", platform, sequence, f"saved detail for {item.title}"
            )


class FakeToutiao:
    def __init__(self, items=(), error: Exception | None = None):
        self.items = tuple(items)
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def search(self, primary_keyword: str, collected_at: str) -> ProviderCapture:
        self.calls.append((primary_keyword, collected_at))
        if self.error:
            raise self.error
        return ProviderCapture(json.dumps({"count": len(self.items)}), ".json", self.items)


class SlowToutiao(FakeToutiao):
    def search(self, primary_keyword: str, collected_at: str) -> ProviderCapture:
        capture = super().search(primary_keyword, collected_at)
        time.sleep(0.1)
        return capture


def test_generation_searches_once_with_exact_keyword_and_writes_atomic_artifacts(tmp_path):
    repository = FileRepository(tmp_path)
    board = _item("toutiao_board", "toutiao", "AI工具 官方榜", 2, group_id="shared")
    search = replace(
        _item("toutiao_search", "toutiao", "AI工具 搜索结果", 1),
        heat=HeatMetrics(1, "1", "search_rank", {"search_rank": 1}),
        raw_payload={"group_id": "shared"},
    )
    juejin = _item("juejin_1", "juejin", "AI工具 掘金榜", 1)
    _save_daily(repository, (board,), (juejin,))
    provider = FakeToutiao((search,))

    bundle = generate_v1_user_result(_profile(), NOW, repository, provider)

    assert bundle.status == "generated"
    assert provider.calls == [("AI工具", NOW.isoformat())]
    assert [item.platform for item in bundle.recommendations] == ["toutiao", "juejin"]
    assert [item.heat_level for item in bundle.recommendations] == [1, 1]
    result_dir = tmp_path / "user_results/u1/2026-07-13"
    assert (result_dir / "report.md").is_file()
    assert (result_dir / "result.json").is_file()
    assert sorted(path.name for path in (result_dir / "topics").iterdir()) == [
        "juejin_002.txt",
        "toutiao_001.txt",
    ]
    assert not list(result_dir.parent.glob("*.tmp-*"))

    cached = generate_v1_user_result(_profile(), NOW, repository, provider)
    assert cached.status == "existing"
    assert provider.calls == [("AI工具", NOW.isoformat())]


def test_independent_generators_share_filesystem_claim_without_duplicate_search(
    tmp_path, monkeypatch
):
    repository = FileRepository(tmp_path)
    board = _item("toutiao_1", "toutiao", "AI工具 官方榜", 1)
    _save_daily(repository, (board,), ())
    provider = SlowToutiao()
    start = threading.Barrier(2)
    monkeypatch.setattr(
        recommendation_module, "_generation_lock", lambda _user_id, _day: threading.Lock()
    )

    def generate():
        start.wait()
        return generate_v1_user_result(_profile(), NOW, repository, provider)

    with ThreadPoolExecutor(max_workers=2) as executor:
        bundles = tuple(executor.map(lambda _index: generate(), range(2)))

    assert len(provider.calls) == 1
    assert {bundle.status for bundle in bundles} == {"generated", "existing"}
    assert (tmp_path / "user_results/u1/2026-07-13.lock").is_file()


def test_multiple_contenders_never_unlink_or_replace_the_owner_lock(tmp_path, monkeypatch):
    repository = FileRepository(tmp_path)
    board = _item("toutiao_1", "toutiao", "AI工具 官方榜", 1)
    _save_daily(repository, (board,), ())
    provider = SlowToutiao()
    start = threading.Barrier(3)
    monkeypatch.setattr(
        recommendation_module, "_generation_lock", lambda _user_id, _day: threading.Lock()
    )
    monkeypatch.setattr(
        Path,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("owner lock path must never be unlinked")
        ),
    )

    def generate():
        start.wait()
        return generate_v1_user_result(_profile(), NOW, repository, provider)

    with ThreadPoolExecutor(max_workers=3) as executor:
        bundles = tuple(executor.map(lambda _index: generate(), range(3)))

    assert len(provider.calls) == 1
    assert [bundle.status for bundle in bundles].count("generated") == 1
    assert [bundle.status for bundle in bundles].count("existing") == 2


def test_filesystem_claim_rechecks_result_after_winning_lock(tmp_path, monkeypatch):
    repository = FileRepository(tmp_path)
    original_try = recommendation_module._try_claim_lock

    def publish_then_claim(handle):
        result = tmp_path / "user_results/u1/2026-07-13/result.json"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text("{}", encoding="utf-8")
        return original_try(handle)

    monkeypatch.setattr(recommendation_module, "_try_claim_lock", publish_then_claim)

    with recommendation_module._filesystem_generation_claim(
        repository, "u1", "2026-07-13"
    ) as claimed:
        assert not claimed


def test_live_process_claim_wait_is_bounded_and_preserves_owner_lock(tmp_path, monkeypatch):
    repository = FileRepository(tmp_path)
    lock_path = tmp_path / "user_results/u1/2026-07-13.lock"
    with recommendation_module._filesystem_generation_claim(
        repository, "u1", "2026-07-13"
    ) as owner_claimed:
        assert owner_claimed
        monkeypatch.setattr(recommendation_module, "_CLAIM_WAIT_SECONDS", 0)
        with recommendation_module._filesystem_generation_claim(
            repository, "u1", "2026-07-13"
        ) as competing_claimed:
            assert not competing_claimed

    assert lock_path.is_file()


def test_unmatched_search_is_level_three_potential_with_exact_notice(tmp_path):
    repository = FileRepository(tmp_path)
    _save_daily(repository)
    search = replace(
        _item("toutiao_search", "toutiao", "AI工具 潜在线索", 1),
        heat=HeatMetrics(1, "1", "search_rank", {"search_rank": 1}),
        raw_payload={"group_id": "unmatched"},
    )

    bundle = generate_v1_user_result(_profile(), NOW, repository, FakeToutiao((search,)))

    assert bundle.recommendations == ()
    assert [item.heat_level for item in bundle.potential_topics] == [3]
    assert bundle.potential_topics[0].evidence["notice"] == "来自头条关键词搜索，未发现官方热榜证据"


def test_search_failure_keeps_saved_official_toutiao_and_juejin_matches(tmp_path):
    repository = FileRepository(tmp_path)
    toutiao = _item("toutiao_1", "toutiao", "普通头条", 1)
    juejin = _item("juejin_1", "juejin", "AI工具 掘金榜", 1)
    _save_daily(repository, (toutiao,), (juejin,))
    day = repository.daily_dir("2026-07-13") / "details"
    (day / "toutiao_1.txt").write_text("正文包含 AI工具", encoding="utf-8")
    provider = FakeToutiao(error=RuntimeError("request failed: secret=bad"))

    bundle = generate_v1_user_result(_profile(), NOW, repository, provider)

    assert [item.hot_item_id for item in bundle.recommendations] == [
        "toutiao_1",
        "juejin_1",
    ]
    assert bundle.query_metadata == {"toutiao_search_status": "failed:RuntimeError"}
    assert "secret" not in (tmp_path / "user_results/u1/2026-07-13/result.json").read_text("utf-8")


def test_no_saved_daily_snapshot_returns_not_ready_without_search_or_output(tmp_path):
    repository = FileRepository(tmp_path)
    provider = FakeToutiao()

    bundle = generate_v1_user_result(_profile(), NOW, repository, provider)

    assert bundle.status == "not_ready"
    assert provider.calls == []
    assert not (tmp_path / "user_results").exists()


def test_before_cutoff_reuses_latest_historical_result_without_search(tmp_path):
    repository = FileRepository(tmp_path)
    previous = generate_v1_user_result
    prior_payload = {
        "status": "generated",
        "user_id": "u1",
        "business_date": "2026-07-11",
        "generated_at": "2026-07-12T08:05:00+08:00",
        "recommendations": [],
        "potential_topics": [],
        "general_fallback": [],
        "query_metadata": {},
    }
    repository.write_user_result_atomic(
        "u1",
        "2026-07-11",
        lambda directory: repository.write_json(directory / "result.json", prior_payload),
    )
    provider = FakeToutiao()

    bundle = generate_v1_user_result(
        _profile(), datetime.fromisoformat("2026-07-13T07:30:00+08:00"), repository, provider
    )

    assert previous is generate_v1_user_result
    assert bundle.status == "existing"
    assert bundle.business_date == "2026-07-11"
    assert provider.calls == []
