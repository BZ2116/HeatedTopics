import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from heated_topics_v3.contracts import (
    ContentValidation,
    DailySnapshot,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    PlatformCollectionStatus,
    QualifiedArticle,
    RecommendationBundle,
    RecommendationItem,
    SearchCacheRecord,
)
from heated_topics_v3.storage import FileRepository


def make_qualified_article(item_id="sina-1", **changes):
    item = HotItem(
        item_id=item_id,
        platform="sina_news",
        title="人工智能突破",
        url="https://example.test/a",
        rank=1,
        heat=HeatMetrics(
            value=100,
            label="100",
            metric_name="top_num",
            metrics={"top_num": 100, "comments": 30},
        ),
        summary="摘要",
        publication_time="2026-07-22T09:00:00+08:00",
        collected_at="2026-07-22T08:00:00+08:00",
        raw_payload={"commentid": "1-2-3"},
    )
    detail = ItemDetail(
        item_id=item_id,
        content="正文段落一。正文段落二。正文段落三。",
        content_status="full_text",
        publication_time="2026-07-22T09:00:00+08:00",
        collected_at="2026-07-22T08:00:00+08:00",
        source_url="https://example.test/a",
        fetch_status="success",
    )
    evidence = HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=1,
        native_hot_value=100.0,
        metrics={"top_num": 100.0, "comments": 30.0},
        threshold_metrics={"comments": 10.0},
        qualified_by=("official_hot_board",),
    )
    validation = ContentValidation(
        status="accepted",
        parser="sina_dom",
        character_count=300,
        paragraph_count=3,
        reasons=(),
    )
    article = QualifiedArticle(
        hot_item=item,
        detail=detail,
        heat_evidence=evidence,
        content_validation=validation,
        platform_heat_score=0.42,
    )
    return replace(article, **changes)


@pytest.fixture
def qualified_article():
    return make_qualified_article()


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


@pytest.mark.parametrize(
    "user_id", ["", ".", "..", "../../outside", r"..\..\outside", "/absolute", r"C:\outside"]
)
def test_user_result_storage_defensively_rejects_unsafe_user_ids(tmp_path, user_id):
    repo = FileRepository(tmp_path / "data")

    with pytest.raises(ValueError, match="user_id"):
        repo.load_user_bundle(user_id, "2026-07-13")
    with pytest.raises(ValueError, match="user_id"):
        repo.load_latest_user_bundle(user_id)
    with pytest.raises(ValueError, match="user_id"):
        repo.write_user_result_atomic(user_id, "2026-07-13", lambda directory: None)

    assert not (tmp_path / "outside").exists()


def test_user_result_storage_rejects_resolved_user_results_outside_data_root(
    tmp_path, monkeypatch
):
    data_root = tmp_path / "data"
    outside = tmp_path / "outside"
    data_root.mkdir()
    outside.mkdir()
    original_resolve = Path.resolve

    def redirected_user_results(path, *args, **kwargs):
        if path == data_root / "user_results":
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected_user_results)
    repo = FileRepository(data_root)

    with pytest.raises(ValueError, match="data root"):
        repo.write_user_result_atomic(
            "safe-user", "2026-07-13", lambda directory: None
        )

    assert not (outside / "safe-user").exists()


def test_eligible_and_rejected_are_separate(tmp_path, qualified_article):
    repository = FileRepository(tmp_path)
    repository.save_eligible("2026-07-23", "sina_news", (qualified_article,))
    repository.save_rejected(
        "2026-07-23",
        "sina_news",
        ({"item_id": "bad", "reasons": ["too_short"]},),
    )

    loaded = repository.load_eligible("2026-07-23", "sina_news")
    assert [item.hot_item.item_id for item in loaded] == [
        qualified_article.hot_item.item_id
    ]
    assert loaded == (qualified_article,)

    rejected = repository._read_json(
        tmp_path / "daily_hot_lists/2026-07-23/rejected/sina_news.json"
    )
    assert rejected == [{"item_id": "bad", "reasons": ["too_short"]}]

    # eligible and rejected occupy distinct subdirectories.
    assert (tmp_path / "daily_hot_lists/2026-07-23/eligible/sina_news.json").is_file()
    assert (tmp_path / "daily_hot_lists/2026-07-23/rejected/sina_news.json").is_file()


def test_search_cache_hashes_keyword_and_distinguishes_states(
    tmp_path, qualified_article
):
    repository = FileRepository(tmp_path)

    repository.save_search_cache(
        "2026-07-23",
        "thepaper",
        " 人工智能 ",
        status="success",
        articles=(qualified_article,),
        rejected=(),
    )
    cache = repository.load_search_cache("2026-07-23", "thepaper", "人工智能")
    assert isinstance(cache, SearchCacheRecord)
    assert cache.status == "success"
    assert cache.articles == (qualified_article,)
    assert cache.normalized_keyword == "人工智能"

    # Directory name is derived from a SHA256 digest; the raw keyword never leaks
    # into the path.
    cache_dir = repository.search_cache_dir("2026-07-23", "thepaper", "人工智能")
    assert "人工智能" not in str(cache_dir)
    # Leading/trailing whitespace normalizes to the same directory.
    assert repository.search_cache_dir(
        "2026-07-23", "thepaper", " 人工智能 "
    ) == cache_dir

    # Empty and failed states are distinguishable from success and from each other.
    repository.save_search_cache(
        "2026-07-23", "thepaper", "空结果", status="empty", articles=(), rejected=()
    )
    empty = repository.load_search_cache("2026-07-23", "thepaper", "空结果")
    assert empty.status == "empty"
    assert empty.articles == ()

    repository.save_search_cache(
        "2026-07-23",
        "thepaper",
        "失败",
        status="failed",
        articles=(),
        rejected=(),
        retry_after="2026-07-23T12:10:00+08:00",
    )
    failed = repository.load_search_cache("2026-07-23", "thepaper", "失败")
    assert failed.status == "failed"
    assert failed.retry_after == "2026-07-23T12:10:00+08:00"

    # A keyword that was never searched has no cache record.
    assert repository.load_search_cache("2026-07-23", "thepaper", "未搜索") is None


def test_news_results_do_not_collide_with_existing_v1_results(tmp_path):
    repository = FileRepository(tmp_path)
    assert repository.news_user_dir("u1") == tmp_path / "news_user_results/u1"
    assert repository.user_dir("u1") == tmp_path / "user_results/u1"


def test_news_user_bundle_round_trips_in_isolated_root(tmp_path):
    repository = FileRepository(tmp_path)

    final = repository.write_news_user_result_atomic(
        "user_001",
        "2026-07-23",
        lambda directory: repository.write_json(
            directory / "result.json", bundle("2026-07-23")
        ),
    )
    assert final == tmp_path / "news_user_results/user_001/2026-07-23"
    assert repository.load_news_user_bundle("user_001", "2026-07-23") == bundle(
        "2026-07-23"
    )
    # V1 result store is untouched.
    assert repository.load_user_bundle("user_001", "2026-07-23") is None


def test_news_user_bundle_rejects_unsafe_user_ids(tmp_path):
    repository = FileRepository(tmp_path / "data")
    with pytest.raises(ValueError, match="user_id"):
        repository.news_user_dir("../../outside")
    with pytest.raises(ValueError, match="user_id"):
        repository.load_news_user_bundle("../../outside", "2026-07-23")


def test_active_snapshot_resolves_at_most_forty_eight_hours_old(
    tmp_path, qualified_article
):
    repository = FileRepository(tmp_path)
    repository.save_eligible("2026-07-22", "sina_news", (qualified_article,))
    pointer = repository.publish_active_snapshot("sina_news", "2026-07-22")
    assert pointer == tmp_path / "active_snapshots/sina_news.json"

    resolved = repository.resolve_eligible_snapshot(
        "sina_news", "2026-07-23T12:00:00+08:00", max_age_hours=48
    )
    assert resolved is not None
    assert resolved[0] == "2026-07-22"
    assert resolved[1] == (qualified_article,)

    # Beyond the 48-hour window the snapshot is no longer eligible.
    assert (
        repository.resolve_eligible_snapshot(
            "sina_news", "2026-07-25T12:01:00+08:00", max_age_hours=48
        )
        is None
    )

    # A platform without any published snapshot resolves to None.
    assert (
        repository.resolve_eligible_snapshot(
            "thepaper", "2026-07-23T12:00:00+08:00", max_age_hours=48
        )
        is None
    )


def test_stable_detail_uses_safe_item_id(tmp_path):
    repository = FileRepository(tmp_path)
    path = repository.save_stable_detail(
        "2026-07-23", "netease_news", "doc/abc 123", "中文正文"
    )
    assert path == tmp_path / "daily_hot_lists/2026-07-23/details/netease_news_doc_abc_123.txt"
    assert path.read_text("utf-8") == "中文正文"


def test_item_detail_metadata_round_trip(tmp_path):
    from heated_topics_v3.contracts import ItemDetail
    from heated_topics_v3.storage import FileRepository

    repository = FileRepository(tmp_path)
    detail = ItemDetail(
        item_id="zhihu_hot_question_1",
        content="问题描述。\n\n热门回答正文。",
        content_status="full_text",
        publication_time="2026-07-25T10:27:00+08:00",
        collected_at="2026-07-25T12:00:00+08:00",
        source_url="https://www.zhihu.com/question/1",
        fetch_status="success",
        metadata={
            "question": {"view_count": 1985997, "answer_count": 583},
            "answers": [{"answer_id": "11", "author": "示例作者", "voteup_count": 1551}],
        },
    )

    path = repository.save_item_detail_metadata(
        "2026-07-25", "zhihu_hot", detail
    )
    loaded = repository.load_item_detail_metadata(
        "2026-07-25", "zhihu_hot", detail.item_id
    )

    assert path.name == "zhihu_hot_zhihu_hot_question_1.json"
    assert loaded == detail
