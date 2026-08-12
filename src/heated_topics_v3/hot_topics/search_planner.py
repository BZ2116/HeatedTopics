"""Bounded, deterministic search query planning."""

from __future__ import annotations

from .hot_topic_clustering import Topic
from .research_contracts import SearchTask


class SearchPlanner:
    _purposes = ("事件事实", "官方来源", "最新进展", "关键数据", "争议与影响")

    def plan(self, topic: Topic, *, priority_rank: int) -> tuple[SearchTask, ...]:
        if priority_rank <= 10:
            count = 5
        elif priority_rank <= 20:
            count = 3
        elif priority_rank <= 30:
            count = 2
        else:
            count = 2
        return tuple(
            SearchTask(topic.topic_id, f"{topic.title} {purpose}", purpose)
            for purpose in self._purposes[:count]
        )
