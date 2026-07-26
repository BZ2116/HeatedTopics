"""Unit tests for the v2 sina_news / netease_news Markdown report renderers."""
from __future__ import annotations

from heated_topics_v3.contracts import (
    HeatMetrics,
    HotItem,
    ItemDetail,
    PersonaPersonal,
    PersonaProfile,
    UserProfile,
)
from heated_topics_v3.llm_keywords import ExtractedKeyword, PersonaKeywordExtraction
from heated_topics_v3.reporting import (
    BaiduCacheStats,
    render_netease_news_report_v2,
    render_sina_news_report_v2,
)
from heated_topics_v3.toutiao_paths import Candidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _user_profile() -> UserProfile:
    return UserProfile(
        profile_id="news_observer_01",
        display_name="News Observer",
        domains=("tech", "news"),
        audience=("readers",),
        content_modes=("analysis",),
        preferred_platforms=("sina_news", "netease_news"),
        core_keywords=("AI", "芯片"),
    )


def _persona_profile() -> PersonaProfile:
    return PersonaProfile(
        user_id="zhao_001",
        level1="科技AI",
        level2="AI工具应用",
        personal=PersonaPersonal(
            role="经管学生视角的AI工具体验官",
            subject="AI工具",
            scenarios=("写作", "学习", "办公"),
            value="真实使用建议",
        ),
        core_keywords=("AI工具", "AI写作"),
        persona_signature="sig:abc",
    )


def _hot_item(item_id: str, title: str) -> HotItem:
    return HotItem(
        item_id=item_id,
        platform="sina_news",
        item_type="news",
        title=title,
        url=f"https://news.sina.com.cn/{item_id}.html",
        rank=1,
        heat=HeatMetrics(
            value=9_876_543,
            label="9876543",
            metric_name="top_num",
            metrics={"top_num": 9_876_543},
        ),
        summary="媒体A",
        category="科技",
        matched_query_ids=(),
        fetched_at="2026-07-26T00:00:00Z",
        fetch_status="success",
        raw_payload={"title": title, "url": f"https://news.sina.com.cn/{item_id}.html"},
    )


def _candidate(
    item: HotItem,
    *,
    source_path: str = "A",
    matched_keyword: str | None = "AI",
    is_toutiao_hot: bool = False,
    is_hot_board: bool = False,
    persona_matched: bool = True,
    preliminary_score: float = 1.23,
) -> Candidate:
    return Candidate(
        item=item,
        source_path=source_path,
        matched_keyword=matched_keyword,
        is_toutiao_hot=is_toutiao_hot,
        is_hot_board=is_hot_board,
        persona_matched=persona_matched,
        preliminary_score=preliminary_score,
    )


def _extraction() -> PersonaKeywordExtraction:
    return PersonaKeywordExtraction(
        user_id="zhao_001",
        persona_signature="sig:abc",
        generated_at="2026-07-26T00:00:00+08:00",
        keywords=(
            ExtractedKeyword(keyword="AI工具", match_expectation="热榜"),
            ExtractedKeyword(keyword="AI写作", match_expectation="长尾"),
            ExtractedKeyword(keyword="兜底词", match_expectation="兜底"),
        ),
        source="fresh",
    )


# ---------------------------------------------------------------------------
# render_sina_news_report_v2
# ---------------------------------------------------------------------------


def test_render_news_v2_basic():
    item1 = _hot_item("a1", "芯片产业新动向")
    item2 = _hot_item("a2", "AI 监管动态")
    candidates = [
        _candidate(item1, source_path="A", preliminary_score=1.50),
        _candidate(item2, source_path="B", matched_keyword="AI写作",
                   is_toutiao_hot=True, preliminary_score=2.75),
    ]

    body = render_sina_news_report_v2(
        _user_profile(),
        _extraction(),
        candidates,
        fetched_at="2026-07-26T00:00:00Z",
    )

    assert "Sina News 热点日报" in body
    assert "News Observer" in body
    assert "## 提取的检索词" in body
    assert "## 候选来源统计" in body
    assert "## 重点文章" in body
    assert "## 操作建议" in body
    assert "芯片产业新动向" in body
    assert "AI 监管动态" in body
    assert "AI工具" in body
    assert "AI写作" in body
    assert "兜底词" in body


def test_render_news_v2_no_extraction_skips_keyword_table():
    item = _hot_item("a1", "头条新闻")
    candidates = [_candidate(item)]

    body = render_sina_news_report_v2(
        _user_profile(),
        None,
        candidates,
        fetched_at="2026-07-26T00:00:00Z",
    )

    assert "## 提取的检索词" not in body
    assert "关键词来源" not in body
    assert "## 候选来源统计" in body
    assert "## 重点文章" in body
    assert "头条新闻" in body


def test_render_news_v2_cache_stats_appended():
    item = _hot_item("a1", "头条新闻")
    candidates = [_candidate(item)]

    stats = BaiduCacheStats()
    stats.record("board", "fresh")

    body_with_stats = render_sina_news_report_v2(
        _user_profile(),
        _extraction(),
        candidates,
        fetched_at="2026-07-26T00:00:00Z",
        cache_stats=stats,
    )
    assert "## 缓存来源" in body_with_stats

    body_without_stats = render_sina_news_report_v2(
        _user_profile(),
        _extraction(),
        candidates,
        fetched_at="2026-07-26T00:00:00Z",
    )
    assert "## 缓存来源" not in body_without_stats


def test_render_netease_news_report_v2_uses_netease_title():
    item = _hot_item("a1", "国产芯片崛起")
    candidates = [_candidate(item, matched_keyword="芯片")]

    body = render_netease_news_report_v2(
        _user_profile(),
        _extraction(),
        candidates,
        fetched_at="2026-07-26T00:00:00Z",
    )

    assert "NetEase News 热点日报" in body
    assert "国产芯片崛起" in body