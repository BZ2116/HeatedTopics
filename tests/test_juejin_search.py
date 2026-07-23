from dataclasses import replace

from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.juejin import (
    JUEJIN_SEARCH_URL,
    merge_juejin_items,
    parse_juejin_search_response,
)


def _item(article_id: str, rank: int | None) -> HotItem:
    return HotItem(
        item_id=f"juejin_{article_id}",
        platform="juejin",
        item_type="article",
        title=f"T{article_id}",
        url=f"https://juejin.cn/post/{article_id}",
        rank=rank,
        heat=HeatMetrics(
            value=rank,
            label="",
            metric_name="hot_rank",
            metrics={},
        ),
        summary="",
        category="",
        matched_query_ids=(),
        fetched_at="t",
        fetch_status="success",
        raw_payload={"content": {"content_id": article_id}},
    )


def _with_tag(item: HotItem, tag: str) -> HotItem:
    """Helper: 给测试夹具补 source_path tag，模拟 parse 阶段的标注。"""
    return replace(item, raw_payload={**item.raw_payload, "source_path": tag})


def test_parse_search_extracts_articles():
    resp = """{"err_no":0,"data":[
      {"result_type":2,"result_model":{"article_id":"7001","article_info":{
        "title":"AI 实战","view_count":1200,"digg_count":80,"collect_count":30,"comment_count":12}}}
    ]}"""
    items = parse_juejin_search_response(resp, fetched_at="t")
    assert len(items) == 1
    assert items[0].item_id == "juejin_7001"
    assert items[0].raw_payload["source_path"] == "B"  # 对齐 Toutiao：search 标 B
    assert items[0].heat.metrics["views"] == 1200
    assert items[0].heat.metric_name == "search_recall"


def test_merge_dedups_by_article_id_rank_wins():
    # rank_items 标 A、search_items 标 B，模拟 parse 阶段已打 tag
    rank_items = [_with_tag(_item("7001", 1), "A"), _with_tag(_item("7003", 2), "A")]
    search_items = [_with_tag(_item("7001", None), "B"), _with_tag(_item("7002", None), "B")]
    merged = merge_juejin_items(rank_items, search_items)
    ids = [m.item_id for m in merged]
    # rank 命中优先：7001 只保留 rank 版；7002 来自 search；7003 来自 rank
    assert ids == ["juejin_7001", "juejin_7003", "juejin_7002"]
    kept_7001 = next(m for m in merged if m.item_id == "juejin_7001")
    assert kept_7001.rank == 1
    assert kept_7001.raw_payload["source_path"] == "A"  # 7001 由 rank 提供，保留 A
    kept_7002 = next(m for m in merged if m.item_id == "juejin_7002")
    assert kept_7002.raw_payload["source_path"] == "B"  # 7002 仅 search，保留 B
    kept_7003 = next(m for m in merged if m.item_id == "juejin_7003")
    assert kept_7003.raw_payload["source_path"] == "A"


def test_search_url_constant():
    assert JUEJIN_SEARCH_URL == "https://api.juejin.cn/search_api/v1/search"
