"""Ranking topics for Xiaohongshu-oriented content creators."""

from __future__ import annotations

from typing import Mapping, Sequence

from .hot_topic_clustering import Topic


XHS_PLATFORM_WEIGHTS: Mapping[str, float] = {
    "weibo": 1.00,
    "zhihu": 0.95,
    "zhihu_daily": 0.85,
    "toutiao": 0.80,
    "sina_news": 0.78,
    "thepaper": 0.78,
    "netease_news": 0.72,
    "juejin": 0.45,
}


def _platform_score(topic: Topic, platform_max_rank: Mapping[str, int]) -> float:
    scores = []
    for item in topic.items:
        max_rank = max(1, platform_max_rank.get(item.platform, item.rank or 1))
        rank_strength = 1.0 - ((item.rank or max_rank) - 1) / max(1, max_rank - 1)
        scores.append(XHS_PLATFORM_WEIGHTS.get(item.platform, 0.5) * (0.7 * rank_strength + 0.3))
    return max(scores, default=0.0)


def score_xhs_topic(topic: Topic, *, platform_max_rank: Mapping[str, int]) -> float:
    """Score an XHS topic using source weight, rank, and cross-platform coverage."""
    source_score = _platform_score(topic, platform_max_rank)
    coverage_bonus = min(0.16, max(0, topic.platform_count - 1) * 0.08)
    return round((source_score + coverage_bonus) * 100, 4)


def rank_xhs_topics(
    topics: Sequence[Topic], *, limit: int = 50,
    platform_max_rank: Mapping[str, int] | None = None,
) -> tuple[Topic, ...]:
    if limit < 1:
        return ()
    max_rank = dict(platform_max_rank or {})
    if not max_rank:
        for topic in topics:
            for item in topic.items:
                max_rank[item.platform] = max(max_rank.get(item.platform, 0), item.rank or 1)
    scored = [
        topic.__class__(
            topic_id=topic.topic_id, title=topic.title, items=topic.items,
            platforms=topic.platforms, platform_count=topic.platform_count,
            trend_score=score_xhs_topic(topic, platform_max_rank=max_rank),
        )
        for topic in topics
    ]
    return tuple(sorted(scored, key=lambda topic: (-topic.trend_score, topic.topic_id))[:limit])
