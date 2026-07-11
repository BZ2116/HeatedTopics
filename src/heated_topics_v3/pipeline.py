import json
from collections.abc import Callable
from pathlib import Path

from heated_topics_v3.contracts import MatchResult, UserProfile
from heated_topics_v3.matching import match_hot_item_to_queries
from heated_topics_v3.profile_queries import build_topic_queries
from heated_topics_v3.providers.juejin import fetch_juejin_hot_items
from heated_topics_v3.reporting import render_juejin_report
from heated_topics_v3.serialization import to_plain_data


def run_juejin_pipeline(
    profile_path: Path,
    output_dir: Path,
    fetched_at: str,
    fetcher: Callable[[str, int], str] | None = None,
) -> dict[str, Path]:
    profile = load_user_profile(profile_path)
    queries = tuple(build_topic_queries(profile))
    hot_items = fetch_juejin_hot_items(fetched_at=fetched_at, fetcher=fetcher)
    matches = [
        result
        for item in hot_items
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    hot_items_path = output_dir / "juejin_hot_items.json"
    matches_path = output_dir / "juejin_matches.json"
    report_path = output_dir / "juejin_report.md"

    _write_json(hot_items_path, hot_items)
    _write_json(matches_path, matches)
    report_path.write_text(render_juejin_report(profile, matches, fetched_at), encoding="utf-8")

    return {
        "hot_items": hot_items_path,
        "matches": matches_path,
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
