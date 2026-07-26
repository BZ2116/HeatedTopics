from pathlib import Path

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from heated_topics_v3.news_pipeline_output import (
    NewsOutputContext,
    write_news_run,
)
from heated_topics_v3.toutiao_paths import PATH_A, PATH_B, Candidate


def _hot_item(cluster_id: str, title: str, *, hot_value: int, rank: int = 1) -> HotItem:
    return HotItem(
        item_id=f"hb_{cluster_id}",
        platform="toutiao",
        item_type="topic",
        title=title,
        url=f"https://www.toutiao.com/group/{cluster_id}/",
        rank=rank,
        heat=HeatMetrics(
            value=hot_value,
            label=str(hot_value),
            metric_name="hot_value",
            metrics={"hot_value": hot_value},
        ),
        summary="",
        category="",
        matched_query_ids=(),
        fetched_at="2026-07-26T08:00:00+08:00",
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
        fetched_at="2026-07-26T08:00:00+08:00",
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
        item_id="detail_" + title,
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


def _make_ctx() -> NewsOutputContext:
    def canonical_url(url: str) -> str:
        return url.split("?", maxsplit=1)[0].rstrip("/")

    def write_article_text(path: Path, candidate: Candidate, detail: ItemDetail) -> None:
        path.write_text(
            f"Title: {detail.title}\n{detail.content}",
            encoding="utf-8",
        )

    return NewsOutputContext(
        canonical_url=canonical_url,
        write_article_text=write_article_text,
        fetched_at="2026-07-26T00:00:00Z",
    )


def _make_candidates() -> list[Candidate]:
    return [
        Candidate(
            item=_hot_item("1", "AI写作工具霸榜", hot_value=2_000_000, rank=1),
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


def test_write_news_run_layout(tmp_path: Path):
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

    result = write_news_run(
        user_id=user_id,
        date="2026-07-26",
        candidates=candidates,
        top_n=10,
        raw_search_by_keyword={"AI写作": [candidates[1].item]},
        raw_article_info_by_key={
            "https://www.toutiao.com/group/100/": {"article_heat": 2000},
        },
        item_details=item_details,
        report_markdown="# Report\n\nbody",
        ctx=_make_ctx(),
        output_root=tmp_path,
        timestamp_suffix="fixedts",
    )

    expected_run_dir = tmp_path / "users" / user_id / "2026-07-26" / "run_fixedts"
    assert result.run_dir == expected_run_dir

    assert (expected_run_dir / "report.md").exists()
    assert (expected_run_dir / "focused.json").exists()
    assert (expected_run_dir / "raw" / "article_info.json").exists()
    assert (expected_run_dir / "raw" / "search_ai写作.json").exists()

    # No hot_board.json — that's toutiao-only.
    assert not (expected_run_dir / "raw" / "hot_board.json").exists()

    # Each kept candidate with a matching detail must produce an article .txt.
    first_article = expected_run_dir / "articles" / "01_ai写作工具霸榜.txt"
    second_article = expected_run_dir / "articles" / "02_ai写作工具评测.txt"
    assert first_article.exists()
    assert second_article.exists()

    first_text = first_article.read_text(encoding="utf-8")
    assert "AI写作工具霸榜" in first_text


def test_focused_json_structure(tmp_path: Path):
    user_id = "zhao_001"
    candidates = _make_candidates()

    result = write_news_run(
        user_id=user_id,
        date="2026-07-26",
        candidates=candidates,
        top_n=10,
        raw_search_by_keyword={},
        raw_article_info_by_key={},
        item_details=[],
        report_markdown="",
        ctx=_make_ctx(),
        output_root=tmp_path,
        timestamp_suffix="fixedts",
    )

    import json

    focused = json.loads(
        (result.run_dir / "focused.json").read_text(encoding="utf-8")
    )
    assert focused["user_id"] == user_id
    assert focused["date"] == "2026-07-26"
    assert focused["fetched_at"] == "2026-07-26T00:00:00Z"
    assert focused["top_n"] == 2
    assert focused["candidates_total"] == 2

    results = focused["results"]
    assert len(results) == 2

    for row in results:
        assert "rank" in row
        assert "title" in row
        assert "url" in row
        assert "source_path" in row
        assert "score" in row
        assert "is_toutiao_hot" in row
        assert "persona_matched" in row

    assert results[0]["rank"] == 1
    assert results[1]["rank"] == 2


def test_paths_counter(tmp_path: Path):
    user_id = "zhao_001"
    candidates = [
        Candidate(
            item=_hot_item("1", "First", hot_value=2_000_000, rank=1),
            source_path="A",
            is_hot_board=True,
            preliminary_score=7.5,
        ),
        Candidate(
            item=_search_item("100", "Second"),
            source_path="A+B",
            is_toutiao_hot=True,
            preliminary_score=6.6,
        ),
        Candidate(
            item=_search_item("200", "Third"),
            source_path="B",
            is_toutiao_hot=True,
            preliminary_score=6.0,
        ),
    ]

    result = write_news_run(
        user_id=user_id,
        date="2026-07-26",
        candidates=candidates,
        top_n=10,
        raw_search_by_keyword={},
        raw_article_info_by_key={},
        item_details=[],
        report_markdown="",
        ctx=_make_ctx(),
        output_root=tmp_path,
        timestamp_suffix="fixedts",
    )

    # Counts over ALL candidates, splitting source_path on "+".
    # candidate[0]: "A"       -> A:1
    # candidate[1]: "A+B"     -> A:1, B:1
    # candidate[2]: "B"       -> B:1
    assert result.paths == {"A": 2, "B": 2}