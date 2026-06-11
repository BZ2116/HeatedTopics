from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HotRecord:
    platform: str
    rank: int
    title: str
    hot: str
    url: str
    crawl_time: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "rank": self.rank,
            "title": self.title,
            "hot": self.hot,
            "url": self.url,
            "crawl_time": self.crawl_time,
        }


@dataclass(frozen=True)
class SelectedTopic:
    title: str
    platforms: list[str]
    ranks: dict[str, int]
    urls: list[str]
    score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "platforms": self.platforms,
            "ranks": self.ranks,
            "urls": self.urls,
            "score": self.score,
        }


@dataclass(frozen=True)
class TopicSource:
    title: str
    source_url: str
    content_preview: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "content_preview": self.content_preview,
            "status": self.status,
        }


@dataclass(frozen=True)
class TopicCard:
    title: str
    platforms: list[str]
    ranks: dict[str, int]
    summary: str
    background: str
    why_hot: list[str]
    related_entities: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    need_follow_up: bool = True
    confidence: str = "medium"