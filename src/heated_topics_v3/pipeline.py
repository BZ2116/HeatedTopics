import json
from collections.abc import Callable
from pathlib import Path

from heated_topics_v3.contracts import MatchResult, UserProfile
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

TOUTIAO_DETAIL_LIMIT = 10


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
        for match in matches[:TOUTIAO_DETAIL_LIMIT]
    ]

    output_dir = _run_output_dir(output_root, profile.profile_id, "toutiao", fetched_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path_out = output_dir / "profile.json"
    queries_path = output_dir / "queries.json"
    hot_board_items_path = output_dir / "hot_board_items.json"
    search_results_path = output_dir / "search_results.json"
    hot_items_path = output_dir / "hot_items.json"
    matches_path = output_dir / "matches.json"
    item_details_path = output_dir / "item_details.json"
    report_path = output_dir / "report.md"

    _write_json(profile_path_out, profile)
    _write_json(queries_path, queries)
    _write_json(hot_board_items_path, hot_board_items)
    _write_json(search_results_path, search_results)
    _write_json(hot_items_path, hot_items)
    _write_json(matches_path, matches)
    _write_json(item_details_path, item_details)
    report_path.write_text(
        render_toutiao_report(profile, matches, fetched_at, item_details),
        encoding="utf-8",
    )

    return {
        "profile": profile_path_out,
        "queries": queries_path,
        "hot_board_items": hot_board_items_path,
        "search_results": search_results_path,
        "hot_items": hot_items_path,
        "matches": matches_path,
        "item_details": item_details_path,
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
    profile_path_out = output_dir / "profile.json"
    queries_path = output_dir / "queries.json"
    hot_items_path = output_dir / "hot_items.json"
    matches_path = output_dir / "matches.json"
    item_details_path = output_dir / "item_details.json"
    report_path = output_dir / "report.md"

    _write_json(profile_path_out, profile)
    _write_json(queries_path, queries)
    _write_json(hot_items_path, hot_items)
    _write_json(matches_path, matches)
    _write_json(item_details_path, item_details)
    report_path.write_text(
        report_renderer(profile, matches, fetched_at, item_details),
        encoding="utf-8",
    )

    return {
        "profile": profile_path_out,
        "queries": queries_path,
        "hot_items": hot_items_path,
        "matches": matches_path,
        "item_details": item_details_path,
        "report": report_path,
    }


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
