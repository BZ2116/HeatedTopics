"""Map V3 Article dicts to OpenBiliClaw DiscoveredContent."""

from __future__ import annotations

from typing import Any

from openbiliclaw.discovery.engine import DiscoveredContent

from heated_topics_v3.openbiliclaw_integration.exceptions import CandidateMappingError

_REQUIRED_FIELDS = ("article_id", "title", "url", "body_text")


def to_discovered(
    articles: list[dict[str, Any]],
    *,
    platform: str,
) -> list[DiscoveredContent]:
    """Convert a list of V3 Article dicts to DiscoveredContent.

    Skips articles that lack required fields. Logs (does not raise) on
    individual skips; raises CandidateMappingError only if the input list
    is not a list.
    """
    if not isinstance(articles, list):
        raise CandidateMappingError(
            f"articles must be a list, got {type(articles).__name__}"
        )
    out: list[DiscoveredContent] = []
    for raw in articles:
        if not isinstance(raw, dict):
            continue
        missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            continue
        heat = raw.get("heat") or {}
        item = DiscoveredContent(
            title=str(raw["title"]),
            content_id=str(raw["article_id"]),
            content_url=str(raw["url"]),
            source_platform=platform,
            body_text=str(raw["body_text"]),
            description=str(raw.get("summary", raw.get("description", ""))),
            author_name=str(raw.get("author", "")),
            published_at=str(raw.get("published_at", "")),
            tags=list(raw.get("tags", [])),
            view_count=int(heat.get("view", 0)),
            like_count=int(heat.get("like", 0)),
            comment_count=int(heat.get("comment", 0)),
            favorite_count=int(heat.get("favorite", 0)),
            share_count=int(heat.get("share", 0)),
            source_rank=int(heat.get("rank", 0)),
            content_type="note",
        )
        out.append(item)
    return out
