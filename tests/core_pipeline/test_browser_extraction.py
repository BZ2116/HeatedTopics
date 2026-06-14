import unittest

from src.core_pipeline.providers.weibo import extract_weibo_posts_from_text
from src.core_pipeline.providers.xiaohongshu import extract_xiaohongshu_notes_from_text


class BrowserExtractionTests(unittest.TestCase):
    def test_extract_weibo_posts_from_text_chunks_content(self):
        text = "用户A\n测试热点正文一\n赞 10 评论 2\n用户B\n测试热点正文二\n赞 3 评论 1"

        posts = extract_weibo_posts_from_text(text)

        self.assertGreaterEqual(len(posts), 1)
        self.assertIn("测试热点正文一", posts[0]["content"])

    def test_extract_xiaohongshu_notes_from_text_chunks_content(self):
        text = "笔记标题\n测试热点笔记正文\n赞 20 收藏 5\n评论 这件事很热"

        notes = extract_xiaohongshu_notes_from_text(text)

        self.assertGreaterEqual(len(notes), 1)
        self.assertIn("测试热点笔记正文", notes[0]["content"])


if __name__ == "__main__":
    unittest.main()