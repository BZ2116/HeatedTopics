"""Contracts shared by platform providers."""
from dataclasses import dataclass

from heated_topics_v3.contracts import HotItem


@dataclass(frozen=True)
class ProviderCapture:
    raw_text: str
    raw_suffix: str
    items: tuple[HotItem, ...]
