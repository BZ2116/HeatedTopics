"""Contracts for the standalone cross-platform hot-topic pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedHotItem:
    item_id: str
    platform: str
    title: str
    normalized_title: str
    url: str
    rank: int | None
    hot_value: float | None
    summary: str
    collected_at: str

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("item_id must not be empty")
        if not self.platform.strip():
            raise ValueError("platform must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.normalized_title.strip():
            raise ValueError("normalized_title must not be empty")
        if not self.url.strip():
            raise ValueError("url must not be empty")
        if self.rank is not None and self.rank < 1:
            raise ValueError("rank must be positive when present")

