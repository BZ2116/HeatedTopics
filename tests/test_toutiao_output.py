import json
import os
from pathlib import Path
from unittest.mock import patch

from heated_topics_v3.contracts import HeatMetrics, HotBoardSnapshot, HotItem, ItemDetail
from heated_topics_v3.hot_board_cache import save_hot_board_snapshot
from heated_topics_v3.toutiao_output import ToutiaoRunResult, write_toutiao_run
from heated_topics_v3.toutiao_paths import PATH_A, PATH_B, Candidate


def _hb_item(cluster_id: str, title: str, hot_value: int, rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"hb_{cluster_id}",
        platform="toutiao",
        item_type="topic",
        title=title,
        url=f"https://www.toutiao.com/group/{cluster_id}/",
        rank=rank,
        heat=HeatMetrics(
            value=hot_value, label=str(hot_value), metric_name="hot_value",
            metrics={"hot_value": hot_value},
        ),
        summary="",
        category="",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={"ClusterId": cluster_id, "source_kind": "hot_board"},
    )


def _search_item(article_id: str, title: str) -> HotItem:
    return HotItem(
        item_id=f"search_{article_id}",
        platform="toutiao",
        item_type="search_result",
        title=title,
        url=f"https://www.toutiao.com/group/{article_id}/",
        rank=1,
        heat=HeatMetrics(value=2000, label="2000", metric_name="article_heat", metrics={}),
        summary="",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={
            "source_kind": "article_info",
            "article_heat": 2000,
            "is_toutiao_hot": True,
            "raw_counts": {"impression_count": 100, "digg_count": 10, "comment_count": 5},
        },
    )


def _item_detail(url: str, title: str, content: str) -> ItemDetail:
    return ItemDetail(
        item_id="detail_1",
        platform="toutiao",
        url=url,
        title=title,
        author="",
        content=content,
        published_at="",
        tags=(),
        extraction_method="test",
        fetch_status="success",
        raw_payload={},
    )


def _snapshot(date: str = "2026-07-13") -> HotBoardSnapshot:
    return HotBoardSnapshot(
        date=date,
        fetched_at=f"{date}T08:00:00+08:00",
        items=(_hb_item("1", "Hot Topic A", 2_000_000, rank=1),),
    )


def _make_candidates() -> list[Candidate]:
    return [
        Candidate(
            item=_hb_item("1", "AI写作工具霸榜", 2_000_000, rank=1),
            source_path=PATH_A,
            matched_keyword="AI写作",
            is_hot_board=True,
            persona_matched=True,
            preliminary_score=7.5,
        ),
        Candidate(
            item=_search_item("100", "AI写作工具评测"),
            source_path=PATH_B,
            matched_keyword="AI写作",
            is_toutiao_hot=True,
            preliminary_score=6.6,
        ),
    ]


def test_write_toutiao_run_creates_per_user_directory_layout(tmp_path: Path):
    user_id = "zhao_001"
    candidates = _make_candidates()
    item_details = [
        _item_detail(
            "https://www.toutiao.com/group/1/", "AI写作工具霸榜", "Top body",
        ),
        _item_detail(
            "https://www.toutiao.com/group/100/", "AI写作工具评测", "Search body",
        ),
    ]
    save_hot_board_snapshot(tmp_path, _snapshot())

    result = write_toutiao_run(
        user_id=user_id,
        date="2026-07-13",
        candidates=candidates,
        top_n=10,
        hot_board_snapshot=_snapshot(),
        raw_search_by_keyword={"AI写作": [candidates[1].item]},
        raw_article_info_by_url={"https://www.toutiao.com/group/100/": {"article_heat": 2000}},
        item_details=item_details,
        report_markdown="# Report\n\nbody",
        output_root=tmp_path,
        timestamp_suffix="120000",
        hot_board_cache_root=tmp_path,
    )

    run_dir = tmp_path / "users" / user_id / "2026-07-13" / "run_120000"
    assert result.run_dir == run_dir
    assert (run_dir / "report.md").exists()
    assert (run_dir / "focused.json").exists()
    assert (run_dir / "raw" / "hot_board.json").exists()
    assert (run_dir / "raw" / "article_info.json").exists()
    assert (run_dir / "raw" / "search_AI写作.json").exists()
    assert (run_dir / "articles" / "01_AI写作工具霸榜.txt").exists()
    assert (run_dir / "articles" / "02_AI写作工具评测.txt").exists()
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# Report" in report_text


def _search_item_jump(article_id: str, title: str) -> HotItem:
    """Path B candidate whose URL is still wrapped in Toutiao's /search/jump shim."""
    return HotItem(
        item_id=f"search_{article_id}",
        platform="toutiao",
        item_type="search_result",
        title=title,
        url=(
            f"/search/jump?aid=1455&jtoken=TOK_{article_id}"
            f"&url=https%3A%2F%2Farticle.zlink.toutiao.com%2Fabcd"
            f"%3Fh5_url%3Dhttps%253A%252F%252Ftoutiao.com%252Fgroup%252F{article_id}%252F"
        ),
        rank=1,
        heat=HeatMetrics(value=2000, label="2000", metric_name="article_heat", metrics={}),
        summary="",
        category="search",
        matched_query_ids=(),
        fetched_at="2026-07-13T08:00:00+08:00",
        fetch_status="success",
        raw_payload={
            "source_kind": "article_info",
            "article_heat": 2000,
            "is_toutiao_hot": False,
            "raw_counts": {"impression_count": 100, "digg_count": 10},
        },
    )


def test_write_toutiao_run_does_not_collapse_search_jump_urls(tmp_path: Path):
    """Regression: /search/jump wrappers must not collapse distinct articles.

    Without resolving the shim, every Path B candidate canonicalizes to
    `/search/jump` and the lookup dict keeps only the last detail — so each
    candidate's article file would carry the same (wrong) body.
    """
    articles = [
        ("111", "第一篇", "body of article 111"),
        ("222", "第二篇", "body of article 222"),
        ("333", "第三篇", "body of article 333"),
    ]
    candidates = [
        Candidate(
            item=_search_item_jump(aid, title),
            source_path=PATH_B,
            matched_keyword="节气",
            is_toutiao_hot=False,
            preliminary_score=score,
        )
        for score, (aid, title, _) in enumerate(articles, start=10)
    ]
    item_details = [
        _item_detail(candidates[i].item.url, title, body)
        for i, (_, title, body) in enumerate(articles)
    ]

    write_toutiao_run(
        user_id="feiyi_001",
        date="2026-07-15",
        candidates=candidates,
        top_n=10,
        hot_board_snapshot=None,
        raw_search_by_keyword={},
        raw_article_info_by_url={},
        item_details=item_details,
        report_markdown="",
        output_root=tmp_path,
        timestamp_suffix="120000",
        hot_board_cache_root=tmp_path,
    )

    articles_dir = tmp_path / "users" / "feiyi_001" / "2026-07-15" / "run_120000" / "articles"
    bodies = {p.read_text(encoding="utf-8") for p in articles_dir.glob("*.txt")}
    for _, _, body in articles:
        assert any(body in text for text in bodies), (
            f"expected body {body!r} to appear in at least one article file; "
            f"got {sorted(p.name for p in articles_dir.glob('*.txt'))}"
        )
    distinct_bodies = {text for text in bodies}
    assert len(distinct_bodies) == len(articles), (
        "all article files collapsed to the same body — /search/jump lookup bug regressed"
    )


def test_focused_json_contains_top_n_results_with_scores(tmp_path: Path):
    candidates = _make_candidates()
    item_details = [
        _item_detail("https://www.toutiao.com/group/1/", "AI写作工具霸榜", "body"),
        _item_detail("https://www.toutiao.com/group/100/", "AI写作工具评测", "body"),
    ]
    save_hot_board_snapshot(tmp_path, _snapshot())

    write_toutiao_run(
        user_id="zhao_001",
        date="2026-07-13",
        candidates=candidates,
        top_n=10,
        hot_board_snapshot=_snapshot(),
        raw_search_by_keyword={"AI写作": []},
        raw_article_info_by_url={},
        item_details=item_details,
        report_markdown="",
        output_root=tmp_path,
        timestamp_suffix="120000",
        hot_board_cache_root=tmp_path,
    )

    focused = json.loads((tmp_path / "users" / "zhao_001" / "2026-07-13" / "run_120000" / "focused.json").read_text(encoding="utf-8"))
    assert focused["user_id"] == "zhao_001"
    assert focused["date"] == "2026-07-13"
    assert focused["top_n"] == 2
    assert focused["candidates_total"] == 2
    rows = focused["results"]
    assert rows[0]["rank"] == 1
    assert rows[0]["source_path"] == PATH_A
    assert rows[0]["hot_value"] == 2_000_000
    assert rows[1]["source_path"] == PATH_B
    assert rows[1]["article_heat"] == 2000


def test_hot_board_symlink_falls_back_to_copy_on_windows(tmp_path: Path, monkeypatch):
    save_hot_board_snapshot(tmp_path, _snapshot())

    def boom(_self, _target):
        raise OSError("symlink not supported")

    monkeypatch.setattr(Path, "symlink_to", boom)

    candidates = _make_candidates()
    item_details = [_item_detail("https://www.toutiao.com/group/1/", "T", "b")]
    write_toutiao_run(
        user_id="zhao_001",
        date="2026-07-13",
        candidates=candidates,
        top_n=10,
        hot_board_snapshot=_snapshot(),
        raw_search_by_keyword={},
        raw_article_info_by_url={},
        item_details=item_details,
        report_markdown="",
        output_root=tmp_path,
        timestamp_suffix="120000",
        hot_board_cache_root=tmp_path,
    )

    target = tmp_path / "users" / "zhao_001" / "2026-07-13" / "run_120000" / "raw" / "hot_board.json"
    assert target.exists()
    # When symlink fails, it should be a real file (not a symlink)
    assert not target.is_symlink()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-07-13"
    assert len(payload["items"]) == 1