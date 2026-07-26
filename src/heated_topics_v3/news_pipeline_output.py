"""Platform-agnostic run-output writer.

Shared by Toutiao (wraps this and adds the hot-board snapshot) and by future
Sina / NetEase pipelines. Keeps the directory layout, focused.json shape,
raw search/article dumps, per-article text files, and report.md writing in
one place so platform-specific writers only contribute the parts that are
actually different (Toutiao: hot_board.json symlink/copy + article text
formatting; others: just delegate here).

Layout:
    output_root/users/{user_id}/{date}/
        report.md
        focused.json
        raw/
            search_{kw}.json
            article_info.json
        articles/
            01_{slug}.txt
            ...
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from heated_topics_v3.contracts import ItemDetail
from heated_topics_v3.serialization import to_plain_data
from heated_topics_v3.toutiao_paths import Candidate


@dataclass(frozen=True)
class NewsRunResult:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]


@dataclass(frozen=True)
class NewsOutputContext:
    """Platform-specific hooks the writer needs from each pipeline."""

    canonical_url: Callable[[str], str]
    write_article_text: Callable[[Path, Candidate, ItemDetail], None]
    fetched_at: str = ""


def write_news_run(
    *,
    user_id: str,
    date: str,
    candidates: list[Candidate],
    top_n: int,
    raw_search_by_keyword: dict[str, list[Any]],
    raw_article_info_by_key: dict[str, dict[str, Any]],
    item_details: list[ItemDetail],
    report_markdown: str,
    ctx: NewsOutputContext,
    output_root: str | Path = "output",
    timestamp_suffix: str | None = None,
    keyword_slug_fn: Callable[[str], str] | None = None,
) -> NewsRunResult:
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
        fetched_at=ctx.fetched_at,
    )

    for keyword, items in raw_search_by_keyword.items():
        slug = keyword_slug_fn(keyword)
        path = raw_dir / f"search_{slug}.json"
        path.write_text(
            json.dumps(to_plain_data(items), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    (raw_dir / "article_info.json").write_text(
        json.dumps(
            {k: dict(v) for k, v in raw_article_info_by_key.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    details_by_url = {ctx.canonical_url(d.url): d for d in item_details}
    for index, candidate in enumerate(kept_candidates, start=1):
        detail = details_by_url.get(ctx.canonical_url(candidate.item.url))
        if detail is None:
            continue
        slug = _slugify(candidate.item.title)[:80] or f"item_{index}"
        txt_path = articles_dir / f"{index:02d}_{slug}.txt"
        ctx.write_article_text(txt_path, candidate, detail)

    (run_dir / "report.md").write_text(report_markdown, encoding="utf-8")

    paths_counts: dict[str, int] = {}
    for c in candidates:
        for token in c.source_path.split("+"):
            paths_counts[token] = paths_counts.get(token, 0) + 1

    return NewsRunResult(
        user_id=user_id,
        date=date,
        run_dir=run_dir,
        top_n=top_n,
        candidates_total=len(candidates),
        kept_total=len(kept_candidates),
        paths=paths_counts,
    )


def _write_focused_json(
    path: Path,
    *,
    user_id: str,
    date: str,
    candidates: list[Candidate],
    candidates_total: int,
    fetched_at: str,
) -> None:
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


def _slugify(value: str) -> str:
    slug = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_").lower()
    return slug or "keyword"


def _now_suffix() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")


# Type alias for keyword slug function
KeywordSlugFn = Callable[[str], str]