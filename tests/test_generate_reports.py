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


def test_render_topic_cards_contains_required_sections():
    markdown = render_topic_cards([sample_card()])
    assert "# 热点详情卡" in markdown
    assert "## AI 新产品发布" in markdown
    assert "**为什么火：**" in markdown
    assert "**置信度：** medium" in markdown


def test_render_daily_digest_contains_required_sections():
    markdown = render_daily_digest([sample_card()])
    assert "# 当前国内热点话题简报" in markdown
    assert "## 今日概览" in markdown
    assert "## 建议继续跟踪" in markdown