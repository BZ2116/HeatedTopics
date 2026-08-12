"""Deterministic cross-platform topic scoring."""

from __future__ import annotations

from typing import Sequence

from .hot_topic_clustering import Topic


def _rank_strength(topic: Topic) -> float:
    values = [1.0 / item.rank for item in topic.items if item.rank and item.rank > 0]
    return min(1.0, max(values, default=0.0))


def _heat_strength(topic: Topic) -> float:
    values = [item.hot_value for item in topic.items if item.hot_value is not None]
    if not values:
        return 0.0
    return min(1.0, max(values) / 1_000_000)


def score_topic(topic: Topic, *, max_platforms: int) -> float:
    coverage = min(1.0, topic.platform_count / max(1, max_platforms))
    score = 60 * coverage + 20 * _rank_strength(topic) + 20 * _heat_strength(topic)
    return round(score, 4)


def rank_topics(topics: Sequence[Topic], *, limit: int = 30) -> tuple[Topic, ...]:
    if limit < 1:
        return ()
    max_platforms = max((topic.platform_count for topic in topics), default=1)
    scored = [
        Topic(
            topic_id=topic.topic_id,
            title=topic.title,
            items=topic.items,
            platforms=topic.platforms,
            platform_count=topic.platform_count,
            trend_score=score_topic(topic, max_platforms=max_platforms),
        )
        for topic in topics
    ]
    return tuple(sorted(scored, key=lambda topic: (-topic.trend_score, topic.topic_id))[:limit])
