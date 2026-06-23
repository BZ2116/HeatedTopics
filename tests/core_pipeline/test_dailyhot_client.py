import unittest

import pytest

from src.core_pipeline.cache_store import CacheStore
from src.core_pipeline.dailyhot_client import collect_dailyhot_records, normalize_dailyhot_response, parse_baidu_top_html


class DailyHotClientTests(unittest.TestCase):
    def test_normalize_dailyhot_response_preserves_desc_and_urls(self):
        payload = {
            "name": "baidu",
            "data": [
                {
                    "id": 1,
                    "title": "百度热点",
                    "url": "https://top.baidu.com/item",
                    "mobileUrl": "https://m.baidu.com/item",
                    "desc": "百度摘要",
                    "hot": "100",
                    "cover": "https://image.example.com/a.png",
                    "author": "来源",
                    "timestamp": "1780000000000",
                }
            ],
        }

        records = normalize_dailyhot_response("baidu", payload, "2026-06-14T20:00:00+08:00")

        self.assertEqual(records[0].id, "hot_baidu_001")
        self.assertEqual(records[0].category, "core_discovery")
        self.assertEqual(records[0].desc, "百度摘要")
        self.assertEqual(records[0].mobile_url, "https://m.baidu.com/item")

    def test_normalize_unknown_route_marks_unknown_category(self):
        payload = {"name": "unknown", "data": [{"title": "未知热点"}]}

        records = normalize_dailyhot_response("unknown", payload, "2026-06-14T20:00:00+08:00")

        self.assertEqual(records[0].category, "unknown")
        self.assertEqual(records[0].fetch_status, "ok")


class DailyHotCollectionTests(unittest.TestCase):
    def test_collect_dailyhot_records_collects_multiple_routes(self):
        payloads = {
            "weibo": {"data": [{"title": "微博热点", "hot": "100"}]},
            "baidu": {"data": [{"title": "百度热点", "hot": "90"}]},
        }

        def fetcher(route: str):
            return payloads[route]

        records = collect_dailyhot_records(
            routes=("weibo", "baidu"),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=fetcher,
        )

        self.assertEqual([record.title for record in records], ["微博热点", "百度热点"])

    def test_collect_dailyhot_records_records_route_failures(self):
        def fetcher(route: str):
            raise RuntimeError("network down")

        records = collect_dailyhot_records(
            routes=("weibo",),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=fetcher,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id, "hot_weibo_failed")
        self.assertEqual(records[0].fetch_status, "failed")
        self.assertEqual(records[0].error_type, "RuntimeError")

    def test_parse_baidu_top_html_extracts_title_desc_url_and_hot_index(self):
        html = """
        <div class="category-wrap_iQLoo horizontal_1eKyQ">
          <a class="img-wrapper_29V76" href="https://www.baidu.com/s?wd=%E6%B5%8B%E8%AF%95&amp;sa=fyb_news" target="_blank">
            <div class="index_1Ew5p c-index-bg1">  1 </div>
          </a>
          <div class="trend_2RttY"><div class="hot-index_1Bl1a"> 123456 </div><div>热搜指数</div></div>
          <div class="content_1YWBm">
            <a href="https://www.baidu.com/s?wd=%E6%B5%8B%E8%AF%95&amp;sa=fyb_news" class="title_dIF3B" target="_blank">
              <div class="c-single-text-ellipsis">  测试百度热搜标题 </div>
            </a>
            <div class="hot-desc_1m_jR large_nSuFU ellipsis_DupbZ">
              这里是百度热榜给出的详细摘要。 <a class="look-more_3oNWC">查看更多&gt;</a>
            </div>
          </div>
        </div>
        """

        records = parse_baidu_top_html(html, "2026-06-22T20:00:00+08:00")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id, "hot_baidu_001")
        self.assertEqual(records[0].source, "baidu_top")
        self.assertEqual(records[0].title, "测试百度热搜标题")
        self.assertEqual(records[0].desc, "这里是百度热榜给出的详细摘要。")
        self.assertEqual(records[0].hot_value, "123456")
        self.assertIn("wd=%E6%B5%8B%E8%AF%95", records[0].url)
        self.assertIn("category-wrap", records[0].raw_payload["html_fragment"])

    def test_collect_dailyhot_records_falls_back_to_baidu_top_when_dailyhot_baidu_is_empty(self):
        html = """
        <div class="category-wrap_iQLoo">
          <a class="img-wrapper_29V76" href="https://www.baidu.com/s?wd=fallback"></a>
          <div class="hot-index_1Bl1a"> 9000 </div>
          <div class="content_1YWBm">
            <a href="https://www.baidu.com/s?wd=fallback" class="title_dIF3B">
              <div class="c-single-text-ellipsis"> 百度兜底热点 </div>
            </a>
            <div class="hot-desc_1m_jR large_nSuFU"> 百度页面摘要 </div>
          </div>
        </div>
        """

        records = collect_dailyhot_records(
            routes=("baidu",),
            captured_at="2026-06-22T20:00:00+08:00",
            fetcher=lambda route: {"data": [{"url": "https://www.baidu.com/s?wd=undefined"}]},
            baidu_html_fetcher=lambda: html,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "baidu_top")
        self.assertEqual(records[0].title, "百度兜底热点")


def test_collect_dailyhot_records_reuses_route_cache(tmp_path):
    cache = CacheStore(tmp_path, now=lambda: __import__("datetime").datetime(2026, 6, 23, tzinfo=__import__("datetime").timezone.utc))
    cache.write(
        "dailyhot:weibo:today",
        [{"data": {"title": "cached weibo topic", "hot": "100"}}],
        fetched_at="2026-06-23T00:00:00+00:00",
    )
    calls = []

    records = collect_dailyhot_records(
        routes=("weibo",),
        captured_at="2026-06-23T08:00:00+08:00",
        fetcher=lambda route: calls.append(route) or {"data": [{"title": "fresh topic"}]},
        cache_store=cache,
        cache_window="today",
    )

    assert calls == []
    assert records[0].title == "cached weibo topic"


def test_collect_dailyhot_records_caches_final_baidu_fallback_records(tmp_path):
    cache = CacheStore(tmp_path, now=lambda: __import__("datetime").datetime(2026, 6, 23, tzinfo=__import__("datetime").timezone.utc))
    html = """
    <div class="category-wrap_iQLoo">
      <a class="img-wrapper_29V76" href="https://www.baidu.com/s?wd=fallback"></a>
      <div class="hot-index_1Bl1a"> 9000 </div>
      <div class="content_1YWBm">
        <a href="https://www.baidu.com/s?wd=fallback" class="title_dIF3B">
          <div class="c-single-text-ellipsis"> cached baidu fallback topic </div>
        </a>
        <div class="hot-desc_1m_jR large_nSuFU"> fallback summary </div>
      </div>
    </div>
    """

    first = collect_dailyhot_records(
        routes=("baidu",),
        captured_at="2026-06-23T08:00:00+08:00",
        fetcher=lambda route: {"data": [{"url": "https://www.baidu.com/s?wd=undefined"}]},
        baidu_html_fetcher=lambda: html,
        cache_store=cache,
        cache_window="today",
    )
    second = collect_dailyhot_records(
        routes=("baidu",),
        captured_at="2026-06-23T09:00:00+08:00",
        fetcher=lambda route: (_ for _ in ()).throw(AssertionError("DailyHot fetch should use cache")),
        baidu_html_fetcher=lambda: (_ for _ in ()).throw(AssertionError("Baidu fallback should use cache")),
        cache_store=cache,
        cache_window="today",
    )

    assert first[0].source == "baidu_top"
    assert second[0].source == "baidu_top"
    assert second[0].title == "cached baidu fallback topic"


if __name__ == "__main__":
    unittest.main()
