import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heated_topics_v3.hot_cache_cleaning import clean_record


class PlatformCleanerTests(unittest.TestCase):
    def clean(self, platform, body, title="标题"):
        return clean_record({"platform": platform, "title": title, "body_text": body})

    def test_sina_removes_page_chrome_and_footer(self):
        row = self.clean("sina_news", "新闻中心\n标题\n缩小字体 放大字体 收藏 微博 微信 分享 0\n正文第一段。\n正文第二段。\n关键词 : 测试")
        self.assertEqual(row["body_text"], "正文第一段。\n正文第二段。")

    def test_toutiao_rejects_event_card_related_feed(self):
        row = self.clean("toutiao", "事件详情\n00:10\n视频标题\n央视新闻 3小时前\n相关内容\n其他作者\n长篇关联内容")
        self.assertEqual(row["body_text"], "")
        self.assertEqual(row["body_clean_status"], "empty_body")

    def test_netease_stops_before_related_news_and_extracts_source(self):
        row = self.clean("netease_news", "来源：央视新闻\n正文第一段。\n正文第二段。\n编辑 | 张三\n相关新闻标题")
        self.assertEqual(row["body_text"], "正文第一段。\n正文第二段。")
        self.assertEqual(row["body_source"], "央视新闻")

    def test_juejin_removes_leading_metadata_and_trailing_controls(self):
        row = self.clean("juejin", "文章标题\n作者\n2026-08-08\n阅读5分钟\n正文第一段。\n正文第二段。\n阅读\n11k\n粉丝\n目录\n收起", "文章标题")
        self.assertEqual(row["body_text"], "正文第一段。\n正文第二段。")

    def test_zhihu_daily_removes_wrappers(self):
        row = self.clean("zhihu_daily", "作者， 简介 查看知乎原文\n正文第一段。\n正文第二段。\n查看知乎讨论")
        self.assertEqual(row["body_text"], "正文第一段。\n正文第二段。")

    def test_empty_body_is_marked(self):
        row = self.clean("zhihu_hot", "")
        self.assertEqual(row["body_clean_status"], "empty_body")


if __name__ == "__main__":
    unittest.main()
