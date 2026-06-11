import unittest

from src.generate_reports import render_daily_digest, render_topic_cards
from src.hot_topic_types import TopicCard


def sample_card():
    return TopicCard(
        title="AI 新产品发布",
        platforms=["weibo", "baidu"],
        ranks={"weibo": 1, "baidu": 3},
        summary="某 AI 产品发布，引发跨平台讨论。",
        background="该事件与 AI 应用落地有关。",
        why_hot=["跨平台讨论", "涉及 AI 产业", "用户关注度高"],
        related_entities=["AI 公司"],
        sources=["https://example.com"],
        need_follow_up=True,
        confidence="medium",
    )


class GenerateReportsTests(unittest.TestCase):
    def test_render_topic_cards_contains_required_sections(self):
        markdown = render_topic_cards([sample_card()])
        self.assertIn("# 热点详情卡", markdown)
        self.assertIn("## AI 新产品发布", markdown)
        self.assertIn("**为什么火：**", markdown)
        self.assertIn("**置信度：** medium", markdown)

    def test_render_daily_digest_contains_required_sections(self):
        markdown = render_daily_digest([sample_card()])
        self.assertIn("# 当前国内热点话题简报", markdown)
        self.assertIn("## 今日概览", markdown)
        self.assertIn("## 建议继续跟踪", markdown)


if __name__ == "__main__":
    unittest.main()
