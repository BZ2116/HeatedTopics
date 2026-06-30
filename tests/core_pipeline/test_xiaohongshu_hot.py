import unittest

from src.core_pipeline.providers.xiaohongshu_hot import (
    parse_rebang_xiaohongshu_html,
    parse_tophub_xiaohongshu_html,
    fetch_xiaohongshu_hot_records,
)


class XiaohongshuHotProviderTests(unittest.TestCase):
    def test_parse_rebang_html_extracts_title_heat_and_url(self):
        page_html = """
        <main>
          <a class="hot-item" href="https://www.xiaohongshu.com/search_result?keyword=%E9%9C%B2%E8%90%A5">
            <span class="rank">1</span>
            <span class="title">露营穿搭</span>
            <span class="hot">123万热度</span>
          </a>
        </main>
        """

        records = parse_rebang_xiaohongshu_html(page_html, captured_at="2026-06-24T08:00:00+08:00")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "rebang_xiaohongshu")
        self.assertEqual(records[0].platform, "xiaohongshu")
        self.assertEqual(records[0].title, "露营穿搭")
        self.assertEqual(records[0].hot_value, "123万热度")
        self.assertEqual(records[0].rank, 1)
        self.assertIn("xiaohongshu.com", records[0].url)

    def test_parse_tophub_html_extracts_title_heat_and_url(self):
        page_html = """
        <div class="cc-cd-cb-l">
          <a href="https://www.xiaohongshu.com/search_result?keyword=%E9%80%9A%E5%8B%A4">
            <span class="s">2</span>
            <span class="t">通勤包推荐</span>
            <span class="e">89.3万</span>
          </a>
        </div>
        """

        records = parse_tophub_xiaohongshu_html(page_html, captured_at="2026-06-24T08:00:00+08:00")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "tophub_xiaohongshu")
        self.assertEqual(records[0].title, "通勤包推荐")
        self.assertEqual(records[0].hot_value, "89.3万")
        self.assertEqual(records[0].rank, 2)

    def test_parse_tophub_table_rows_extracts_real_rank_shape(self):
        page_html = """
        <table class="table">
          <tbody>
            <tr>
              <td align="center">1.</td>
              <td><a href="https://www.xiaohongshu.com/search_result?keyword=travel&type=51">用万能旅行拍照姿势美美出片</a></td>
              <td class="ws">918.6w</td>
              <td align="right"><a href="https://www.xiaohongshu.com/search_result?keyword=travel&type=51" title="查看详细">详情</a></td>
            </tr>
          </tbody>
        </table>
        """

        records = parse_tophub_xiaohongshu_html(page_html, captured_at="2026-06-24T08:00:00+08:00")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "用万能旅行拍照姿势美美出片")
        self.assertEqual(records[0].hot_value, "918.6w")
        self.assertEqual(records[0].rank, 1)

    def test_fetch_xiaohongshu_hot_records_uses_rebang_before_tophub(self):
        calls = []

        def http_get(url: str) -> str:
            calls.append(url)
            return """
            <a href="https://www.xiaohongshu.com/search_result?keyword=a">
              <span class="rank">1</span>
              <span class="title">榜单话题</span>
              <span class="hot">100</span>
            </a>
            """

        records = fetch_xiaohongshu_hot_records(
            captured_at="2026-06-24T08:00:00+08:00",
            http_get=http_get,
            browser_fetcher=lambda captured_at: [],
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "rebang_xiaohongshu")
        self.assertEqual(len(calls), 1)

    def test_fetch_xiaohongshu_hot_records_falls_back_to_browser(self):
        calls = []

        def http_get(url: str) -> str:
            calls.append(url)
            return "<html></html>"

        def browser_fetcher(captured_at: str):
            from src.core_pipeline.types import HotRecord

            return [
                HotRecord(
                    id="hot_xiaohongshu_browser_001",
                    source="xiaohongshu_browser",
                    platform="xiaohongshu",
                    route="xiaohongshu",
                    category="core_discovery",
                    title="浏览器补采话题",
                    rank=1,
                    hot_value="",
                    url="",
                    mobile_url="",
                    desc="",
                    author="",
                    cover="",
                    timestamp="",
                    captured_at=captured_at,
                    raw_payload={},
                    fetch_status="ok",
                    error_type=None,
                )
            ]

        records = fetch_xiaohongshu_hot_records(
            captured_at="2026-06-24T08:00:00+08:00",
            http_get=http_get,
            browser_fetcher=browser_fetcher,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(records[0].source, "xiaohongshu_browser")


if __name__ == "__main__":
    unittest.main()
