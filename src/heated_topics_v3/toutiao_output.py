"""Per-user Toutiao output writer.

Wraps the platform-agnostic ``write_news_run`` and adds the
``raw/hot_board.json`` snapshot (symlink from the daily hot-board cache,
or a copy fallback on Windows).

Layout:
    output_root/users/{user_id}/{date}/
        report.md
        focused.json
        raw/
            hot_board.json        # symlink → cache/hot_board/{date}.json (or copy)
            search_{kw}.json
            article_info.json
        articles/
            01_{slug}.txt
            ...
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from heated_topics_v3.contracts import HotBoardSnapshot, ItemDetail
from heated_topics_v3.hot_board_cache import hot_board_cache_path
from heated_topics_v3.news_pipeline_output import (
    KeywordSlugFn,
    NewsOutputContext,
    write_news_run,
)
from heated_topics_v3.providers.toutiao import resolve_toutiao_content_url
from heated_topics_v3.serialization import to_plain_data
from heated_topics_v3.toutiao_paths import Candidate


@dataclass(frozen=True)
class ToutiaoRunResult:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str  # "cache" | "fresh" | "fallback_yesterday"


def write_toutiao_run(
    *,
    user_id: str,
    date: str,
    candidates: list[Candidate],
    top_n: int,
    hot_board_snapshot: HotBoardSnapshot | None,
    raw_search_by_keyword: dict[str, list[Any]],
    raw_article_info_by_url: dict[str, dict[str, Any]],
    item_details: list[ItemDetail],
    report_markdown: str,
    output_root: str | Path = "output",
    timestamp_suffix: str | None = None,
    hot_board_cache_root: str | Path = "cache",
    keyword_slug_fn: "KeywordSlugFn | None" = None,
) -> ToutiaoRunResult:
    """Write the per-user per-date run directory and return metadata."""
    ctx = NewsOutputContext(
        canonical_url=_canonical_url,
        write_article_text=_write_article_text,
        fetched_at=hot_board_snapshot.fetched_at if hot_board_snapshot else "",
    )
    result = write_news_run(
        user_id=user_id,
        date=date,
        candidates=candidates,
        top_n=top_n,
        raw_search_by_keyword=raw_search_by_keyword,
        raw_article_info_by_key=raw_article_info_by_url,
        item_details=item_details,
        report_markdown=report_markdown,
        ctx=ctx,
        output_root=output_root,
        timestamp_suffix=timestamp_suffix,
        keyword_slug_fn=keyword_slug_fn,
    )

    if hot_board_snapshot is not None:
        _link_or_copy_hot_board(
            result.run_dir / "raw", date, hot_board_snapshot, hot_board_cache_root,
        )

    return ToutiaoRunResult(
        user_id=result.user_id,
        date=result.date,
        run_dir=result.run_dir,
        top_n=result.top_n,
        candidates_total=result.candidates_total,
        kept_total=result.kept_total,
        paths=result.paths,
        hot_board_source="cache",
    )


def _link_or_copy_hot_board(
    raw_dir: Path,
    date: str,
    snapshot: HotBoardSnapshot,
    cache_root: str | Path,
) -> None:
    cache_path = hot_board_cache_path(cache_root, date)
    target = raw_dir / "hot_board.json"
    if cache_path.exists():
        try:
            target.symlink_to(cache_path)
            return
        except OSError:
            pass
    target.write_text(
        json.dumps(
            {
                "date": snapshot.date,
                "fetched_at": snapshot.fetched_at,
                "items": to_plain_data(list(snapshot.items)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_article_text(path: Path, candidate: Candidate, detail: ItemDetail) -> None:
    raw_payload = candidate.item.raw_payload
    heat_line = (
        f"HotValue: {candidate.item.heat.value}"
        if candidate.is_hot_board
        else f"Article heat (composite): {int(raw_payload.get('article_heat') or 0)}"
    )
    raw_counts = raw_payload.get("raw_counts") or {}
    counts_str = ", ".join(f"{k}={v}" for k, v in raw_counts.items()) if raw_counts else "n/a"
    fetched_at = detail.raw_payload.get("fetched_at") or candidate.item.fetched_at
    body = "\n".join(
        [
            f"Title: {detail.title}",
            f"Keyword: {candidate.matched_keyword or 'n/a'}",
            f"Source path: {candidate.source_path}",
            f"Fetched at: {fetched_at}",
            heat_line,
            f"Raw counts: {counts_str}",
            f"is_toutiao_hot: {candidate.is_toutiao_hot}",
            f"is_original: {raw_payload.get('is_original', False)}",
            "",
            "=" * 60,
            detail.content,
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")


def _canonical_url(url: str) -> str:
    """Stable lookup key for matching candidates to fetched item details.

    Path B search results come wrapped in `/search/jump?jtoken=...&url=...&h5_url=...`
    which collapses to `/search/jump` under naive query-stripping — destroying
    per-article identity and causing the detail lookup dict to keep only one
    body for every search candidate. Resolve the shim first so each article
    collapses to its own group/trending path.
    """
    resolved = resolve_toutiao_content_url(url)
    return resolved.split("?", maxsplit=1)[0].rstrip("/") or url