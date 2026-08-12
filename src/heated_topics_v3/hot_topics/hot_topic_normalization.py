"""Deterministic normalization of platform hot-list items."""

from __future__ import annotations

import re
import unicodedata

from ..contracts import HotItem
from .hot_topics_contracts import NormalizedHotItem


_HASH_MARKERS = re.compile(r"#+")
_NOISE = re.compile(r"[!！?？。；;、,:：·【】\[\]（）(){}<>《》…]+")
_PLATFORM_LABELS = re.compile(r"(?:^|\s)(?:爆|热|沸|新)(?=\s|$)")
_WHITESPACE = re.compile(r"\s+")
_EMOJI = re.compile(
    "["
    "\\U0001F300-\\U0001FAFF"
    "\\U00002700-\\U000027BF"
    "]+",
    flags=re.UNICODE,
)


def normalize_title(title: str) -> str:
    """Remove platform decoration while preserving searchable title tokens."""
    value = unicodedata.normalize("NFKC", title).strip().lower()
    value = _HASH_MARKERS.sub(" ", value)
    value = _EMOJI.sub(" ", value)
    value = _NOISE.sub(" ", value)
    value = _PLATFORM_LABELS.sub(" ", value)
    return _WHITESPACE.sub(" ", value).strip()


def normalize_hot_item(item: HotItem) -> NormalizedHotItem:
    normalized_title = normalize_title(item.title)
    if not normalized_title:
        raise ValueError("hot item title becomes empty after normalization")
    hot_value = item.heat.value
    return NormalizedHotItem(
        item_id=item.item_id,
        platform=item.platform,
        title=item.title.strip(),
        normalized_title=normalized_title,
        url=item.url.strip(),
        rank=item.rank,
        hot_value=float(hot_value) if hot_value is not None else None,
        summary=item.summary.strip(),
        collected_at=item.collected_at,
    )
