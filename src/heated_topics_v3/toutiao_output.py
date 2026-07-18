"""Per-user Toutiao output writer.

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
            summary.md
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from heated_topics_v3.contracts import HotBoardSnapshot, ItemDetail
from heated_topics_v3.hot_board_cache import hot_board_cache_path
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
    if keyword_slug_fn is None:
        keyword_slug_fn = _slugify

    base_dir = Path(output_root) / "users" / user_id / date
    suffix = timestamp_suffix or _now_suffix()
    run_dir = base_dir / f"run_{suffix}"
    raw_dir = run_dir / "raw"
    articles_dir = run_dir / "articles"
    raw_dir.mkdir(parents=True, exist_ok=True)
    articles_dir.mkdir(parents=True, exist_ok=True)

    kept_candidates = candidates[: max(0, top_n)]

    _write_focused_json(
        run_dir / "focused.json",
        user_id=user_id,
        date=date,
        candidates=kept_candidates,
        candidates_total=len(candidates),
        hot_board_snapshot=hot_board_snapshot,
    )

    if hot_board_snapshot is not None:
        _link_or_copy_hot_board(raw_dir, date, hot_board_snapshot, hot_board_cache_root)

    for keyword, items in raw_search_by_keyword.items():
        slug = keyword_slug_fn(keyword)
        path = raw_dir / f"search_{slug}.json"
        path.write_text(
            json.dumps(to_plain_data(items), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    (raw_dir / "article_info.json").write_text(
        json.dumps(
            {url: dict(info) for url, info in raw_article_info_by_url.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    details_by_url = {_canonical_url(d.url): d for d in item_details}
    for index, candidate in enumerate(kept_candidates, start=1):
        detail = details_by_url.get(_canonical_url(candidate.item.url))
        if detail is None:
            continue
        slug = _slugify(candidate.item.title)[:80] or f"item_{index}"
        txt_path = articles_dir / f"{index:02d}_{slug}.txt"
        _write_article_text(txt_path, candidate, detail)

    (run_dir / "report.md").write_text(report_markdown, encoding="utf-8")

    paths_counts: dict[str, int] = {}
    for c in candidates:
        for token in c.source_path.split("+"):
            paths_counts[token] = paths_counts.get(token, 0) + 1

    return ToutiaoRunResult(
        user_id=user_id,
        date=date,
        run_dir=run_dir,
        top_n=top_n,
        candidates_total=len(candidates),
        kept_total=len(kept_candidates),
        paths=paths_counts,
        hot_board_source="cache",
    )


def _write_focused_json(
    path: Path,
    *,
    user_id: str,
    date: str,
    candidates: list[Candidate],
    candidates_total: int,
    hot_board_snapshot: HotBoardSnapshot | None,
) -> None:
    fetched_at = hot_board_snapshot.fetched_at if hot_board_snapshot else ""
    rows = []
    for rank, candidate in enumerate(candidates, start=1):
        item = candidate.item
        raw_payload = dict(item.raw_payload)
        rows.append(
            {
                "rank": rank,
                "title": item.title,
                "url": item.url,
                "source_path": candidate.source_path,
                "matched_keyword": candidate.matched_keyword,
                "score": round(candidate.preliminary_score, 4),
                "is_toutiao_hot": candidate.is_toutiao_hot,
                "hot_value": item.heat.value if candidate.is_hot_board else None,
                "article_heat": int(raw_payload.get("article_heat") or 0) if not candidate.is_hot_board else None,
                "persona_matched": candidate.persona_matched,
                "metric_name": raw_payload.get("metric_name", item.heat.metric_name),
            }
        )
    payload = {
        "user_id": user_id,
        "date": date,
        "fetched_at": fetched_at,
        "top_n": len(candidates),
        "candidates_total": candidates_total,
        "results": rows,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
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


def _slugify(value: str) -> str:
    slug = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_").lower()
    return slug or "keyword"


def _now_suffix() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")


# Type alias for keyword slug function
from typing import Callable
KeywordSlugFn = Callable[[str], str]