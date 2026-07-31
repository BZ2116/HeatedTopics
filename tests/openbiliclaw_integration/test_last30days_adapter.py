"""Field-mapping tests for last30days Item → V3 HotItem/ItemDetail."""

from __future__ import annotations

import json
from pathlib import Path

from heated_topics_v3.contracts import HotItem, ItemDetail
from heated_topics_v3.openbiliclaw_integration import last30days_adapter


def _load(name: str) -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
    )


def test_weibo_item_maps_to_hot_item_and_detail() -> None:
    data = _load("last30days_report_minimal.json")
    items, details = last30days_adapter.to_hot_items(data)
    assert len(items) == 1
    assert len(details) == 1
    item, detail = items[0], details[0]

    assert isinstance(item, HotItem)
    assert isinstance(detail, ItemDetail)
    assert item.platform == "weibo"
    assert item.item_id == "weibo:WB1"
    assert item.title.startswith("测试微博")
    assert item.heat.metrics["views"] == 12000
    assert item.heat.metrics["likes"] == 340
    assert item.rank == 1  # first item in platform result

    assert detail.content_status == "full_text"
    assert "正文" in detail.content
    assert detail.source_url == "https://weibo.com/123/abc"


def test_weibo_item_with_empty_text_is_skipped() -> None:
    """No text → no title, no body → skip entirely (no useful item)."""
    data = _load("last30days_report_minimal.json")
    data["weibo"][0]["text"] = ""
    items, details = last30days_adapter.to_hot_items(data)
    assert items == [] and details == []


def test_to_hot_items_skips_empty_platforms() -> None:
    """Only weibo has 1 item; all others are empty → result has 1 item."""
    data = _load("last30days_report_minimal.json")
    items, _ = last30days_adapter.to_hot_items(data)
    assert len(items) == 1
    assert items[0].platform == "weibo"


def test_to_hot_items_assigns_per_platform_rank() -> None:
    data = _load("last30days_report_minimal.json")
    data["weibo"] = [
        {"id": f"WB{i}", "text": f"t{i}", "url": f"https://w/{i}",
         "author_handle": "u", "engagement": {"views": i}}
        for i in range(3)
    ]
    items, _ = last30days_adapter.to_hot_items(data)
    assert [i.rank for i in items] == [1, 2, 3]
    assert [i.item_id for i in items] == ["weibo:WB0", "weibo:WB1", "weibo:WB2"]


def test_all_seven_platforms_with_items_map_to_hot_items() -> None:
    """Full fixture: 7 of 8 platforms have items (douyin empty)."""
    data = _load("last30days_report_full.json")
    items, details = last30days_adapter.to_hot_items(data)
    platforms = {i.platform for i in items}
    assert platforms == {"weibo", "xiaohongshu", "bilibili", "zhihu",
                         "wechat", "baidu", "toutiao"}
    assert len(items) == 7
    assert len(items) == len(details)


def test_unknown_platform_block_is_skipped() -> None:
    data = _load("last30days_report_full.json")
    data["future_platform"] = [{"id": "F1", "title": "?", "url": "https://x"}]
    items, _ = last30days_adapter.to_hot_items(data)
    assert all(i.platform != "future_platform" for i in items)


def test_toutiao_falls_back_to_abstract_as_body() -> None:
    """If `content` is empty but `abstract` exists, body comes from abstract."""
    data = _load("last30days_report_full.json")
    items, details = last30days_adapter.to_hot_items(data)
    toutiao_idx = next(i for i, x in enumerate(items) if x.platform == "toutiao")
    assert details[toutiao_idx].content_status == "full_text"
    assert details[toutiao_idx].content == "头条摘要"


def test_toutiao_with_no_content_and_no_abstract_marks_title_only() -> None:
    data = _load("last30days_report_full.json")
    data["toutiao"][0]["content"] = ""
    data["toutiao"][0]["abstract"] = ""
    items, details = last30days_adapter.to_hot_items(data)
    toutiao_idx = next(i for i, x in enumerate(items) if x.platform == "toutiao")
    assert details[toutiao_idx].content_status == "title_only"


def test_bilibili_uses_bvid_in_item_id() -> None:
    data = _load("last30days_report_full.json")
    items, _ = last30days_adapter.to_hot_items(data)
    bili = next(x for x in items if x.platform == "bilibili")
    assert bili.item_id == "bilibili:BV1abc"
    assert "AI" in bili.summary or bili.title  # has title


def test_xhs_uses_hashtags_as_tags() -> None:
    data = _load("last30days_report_full.json")
    items, _ = last30days_adapter.to_hot_items(data)
    xhs = next(x for x in items if x.platform == "xiaohongshu")
    # raw_payload carries last30days's hashtags for downstream
    assert "AI" in xhs.raw_payload.get("hashtags", [])
    assert "工具" in xhs.raw_payload.get("hashtags", [])


def test_zhihu_voteups_appear_in_heat_metrics() -> None:
    data = _load("last30days_report_full.json")
    items, _ = last30days_adapter.to_hot_items(data)
    zhihu = next(x for x in items if x.platform == "zhihu")
    assert zhihu.heat.metrics["voteups"] == 100
    assert zhihu.heat.metrics["num_comments"] == 20