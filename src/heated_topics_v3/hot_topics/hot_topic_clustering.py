"""Rule-first clustering for normalized cross-platform hot items."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from typing import Sequence

from .hot_topics_contracts import NormalizedHotItem


@dataclass(frozen=True)
class Topic:
    topic_id: str
    title: str
    items: tuple[NormalizedHotItem, ...]
    platforms: tuple[str, ...]
    platform_count: int
    trend_score: float = 0.0

    @property
    def fingerprint(self) -> str:
        return topic_fingerprint(self.title)


def topic_fingerprint(title: str) -> str:
    """Return a stable cache key independent of rank, platform, and topic_id."""
    normalized = re.sub(r"\s+", "", title.strip().lower())
    normalized = re.sub(r"[!！?？。；;、,:：·【】\[\]（）(){}<>《》…]+", "", normalized)
    tokens = sorted(_tokens(normalized))
    material = "|".join(tokens) or normalized
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _tokens(value: str) -> set[str]:
    words: set[str] = set()
    for segment in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            words.add(segment)
            words.update(segment[i : i + 2] for i in range(len(segment) - 1))
        else:
            words.add(segment)
    return {token for token in words if len(token) > 1}


def _same_topic(left: NormalizedHotItem, right: NormalizedHotItem) -> bool:
    if left.normalized_title == right.normalized_title:
        return True
    shared = _tokens(left.normalized_title) & _tokens(right.normalized_title)
    if len(shared) < 2:
        return False
    left_tokens = _tokens(left.normalized_title)
    right_tokens = _tokens(right.normalized_title)
    overlap = len(shared) / min(len(left_tokens), len(right_tokens))
    return overlap >= 0.5


def cluster_hot_items(items: Sequence[NormalizedHotItem]) -> tuple[Topic, ...]:
    groups: list[list[NormalizedHotItem]] = []
    for item in items:
        group = next((group for group in groups if any(_same_topic(item, existing) for existing in group)), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    topics: list[Topic] = []
    for index, group in enumerate(groups, 1):
        platforms = tuple(dict.fromkeys(item.platform for item in group))
        topics.append(
            Topic(
                topic_id=f"topic_{index:03d}",
                title=group[0].title,
                items=tuple(group),
                platforms=platforms,
                platform_count=len(platforms),
            )
        )
    return tuple(topics)
