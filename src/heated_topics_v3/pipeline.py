import json
from collections.abc import Callable
from pathlib import Path

from heated_topics_v3.contracts import ItemDetail, MatchResult, UserProfile
from heated_topics_v3.matching import match_hot_item_to_queries
from heated_topics_v3.profile_queries import build_topic_queries
from heated_topics_v3.providers.juejin import fetch_juejin_hot_items, fetch_juejin_item_detail
from heated_topics_v3.providers.toutiao import (
    build_toutiao_search_phrases,
    fetch_toutiao_hot_items,
    fetch_toutiao_item_detail,
    fetch_toutiao_search_items,
    merge_toutiao_items,
)
from heated_topics_v3.reporting import render_juejin_report, render_toutiao_report
from heated_topics_v3.serialization import to_plain_data

def run_juejin_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int, dict[str, str] | None], str] | None = None,
) -> dict[str, Path]:
    return _run_platform_pipeline(
        profile_path=profile_path,
        output_root=output_root,
        fetched_at=fetched_at,
        source_id="juejin",
        hot_items_fetcher=lambda fetched_at: fetch_juejin_hot_items(
            fetched_at=fetched_at,
            fetcher=fetcher,
        ),
        item_detail_fetcher=lambda item: fetch_juejin_item_detail(
            item,
            fetcher=detail_fetcher,
        ),
        report_renderer=render_juejin_report,
    )


def run_toutiao_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int], str] | None = None,
) -> dict[str, Path]:
    profile = load_user_profile(profile_path)
    queries = tuple(build_topic_queries(profile))
    phrases = build_toutiao_search_phrases(queries)
    hot_board_items = fetch_toutiao_hot_items(fetched_at=fetched_at, fetcher=fetcher)
    search_results = fetch_toutiao_search_items(
        phrases=phrases,
        fetched_at=fetched_at,
        fetcher=fetcher,
    )
    hot_items = merge_toutiao_items(search_results, hot_board_items)
    matches = [
        result
        for item in hot_items
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]
    item_details = [
        fetch_toutiao_item_detail(match.item, fetcher=detail_fetcher)
        for match in matches
    ]

    output_dir = _run_output_dir(output_root, profile.profile_id, "toutiao", fetched_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    article_texts_dir = output_dir / "article_texts"
    hot_items_path = output_dir / "hot_items.json"
    report_path = output_dir / "report.md"
    hot_item_rows = _build_hot_item_rows(matches, item_details, article_texts_dir)

    _write_json(hot_items_path, hot_item_rows)
    report_path.write_text(
        render_toutiao_report(profile, matches, fetched_at, item_details),
        encoding="utf-8",
    )

    return {
        "article_texts": article_texts_dir,
        "hot_items": hot_items_path,
        "report": report_path,
    }


def _run_platform_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    source_id: str,
    hot_items_fetcher,
    item_detail_fetcher,
    report_renderer,
) -> dict[str, Path]:
    profile = load_user_profile(profile_path)
    queries = tuple(build_topic_queries(profile))
    hot_items = hot_items_fetcher(fetched_at)
    matches = [
        result
        for item in hot_items
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]
    item_details = [
        item_detail_fetcher(match.item)
        for match in matches
    ]

    output_dir = _run_output_dir(output_root, profile.profile_id, source_id, fetched_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    article_texts_dir = output_dir / "article_texts"
    hot_items_path = output_dir / "hot_items.json"
    report_path = output_dir / "report.md"
    hot_item_rows = _build_hot_item_rows(matches, item_details, article_texts_dir)

    _write_json(hot_items_path, hot_item_rows)
    report_path.write_text(
        report_renderer(profile, matches, fetched_at, item_details),
        encoding="utf-8",
    )

    return {
        "article_texts": article_texts_dir,
        "hot_items": hot_items_path,
        "report": report_path,
    }


def _build_hot_item_rows(
    matches: list[MatchResult],
    item_details: list[ItemDetail],
    article_texts_dir: Path,
) -> list[dict[str, object]]:
    article_texts_dir.mkdir(parents=True, exist_ok=True)
    details_by_item_id = {detail.item_id: detail for detail in item_details}
    rows: list[dict[str, object]] = []
    for index, match in enumerate(matches, start=1):
        item = match.item
        detail = details_by_item_id.get(item.item_id)
        txt_path = ""
        content_chars = 0
        fetch_status = "not_fetched"
        extraction_method = ""
        if detail is not None:
            filename = f"{index:03d}_{_safe_filename(detail.title or item.title)}.txt"
            absolute_txt_path = article_texts_dir / filename
            relative_txt_path = Path("article_texts") / filename
            _write_article_text(absolute_txt_path, detail)
            txt_path = relative_txt_path.as_posix()
            content_chars = len(detail.content)
            fetch_status = detail.fetch_status
            extraction_method = detail.extraction_method
        rows.append(
            {
                "item": item,
                "match_terms": match.match_terms,
                "excluded_terms": match.excluded_terms,
                "relevance_score": match.relevance_score,
                "detail": {
                    "fetch_status": fetch_status,
                    "extraction_method": extraction_method,
                    "txt_path": txt_path,
                    "content_chars": content_chars,
                },
            }
        )
    return rows


def _write_article_text(path: Path, detail: ItemDetail) -> None:
    body = "\n".join(
        [
            f"Title: {detail.title}",
            f"Platform: {detail.platform}",
            f"URL: {detail.url}",
            f"Author: {detail.author}",
            f"Published at: {detail.published_at}",
            f"Fetch status: {detail.fetch_status}",
            f"Extraction method: {detail.extraction_method}",
            "",
            "Content:",
            detail.content,
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")


def _safe_filename(value: str) -> str:
    safe = "".join("_" if char in '<>:"/\\|?*' else char for char in value.strip())
    safe = " ".join(safe.split())
    safe = safe.strip(". ")
    return (safe or "article")[:100]


def load_user_profile(profile_path: Path) -> UserProfile:
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    return UserProfile(
        profile_id=str(payload["profile_id"]),
        display_name=str(payload["display_name"]),
        domains=tuple(payload.get("domains", [])),
        audience=tuple(payload.get("audience", [])),
        content_modes=tuple(payload.get("content_modes", [])),
        preferred_platforms=tuple(payload.get("preferred_platforms", [])),
        core_keywords=tuple(payload.get("core_keywords", [])),
        entity_keywords=tuple(payload.get("entity_keywords", [])),
        excluded_keywords=tuple(payload.get("excluded_keywords", [])),
    )


def _write_json(path: Path, rows: object) -> None:
    path.write_text(
        json.dumps(to_plain_data(rows), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_output_dir(output_root: Path, profile_id: str, source_id: str, fetched_at: str) -> Path:
    timestamp = fetched_at.replace("-", "").replace(":", "").split("+", maxsplit=1)[0]
    timestamp = timestamp.replace("T", "_")
    return output_root / profile_id / source_id / f"run_{timestamp}"
