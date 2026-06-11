#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.demo_config import (
    DAILY_DIGEST_HTML_PATH,
    DAILY_DIGEST_PATH,
    DATA_DIR,
    HOT_LIST_PATH,
    HOT_TOPIC_CARDS_PATH,
    MAX_SELECTED_TOPICS,
    MIN_SELECTED_TOPICS,
    PLATFORMS,
    REPORTS_DIR,
    SELECTED_TOPICS_PATH,
    TOPIC_SOURCES_PATH,
)
from src.enrich_sources import enrich_topics
from src.fetch_hot_lists import fetch_all_platforms
from src.generate_reports import build_cards, render_daily_digest, render_static_html, render_topic_cards
from src.hot_topic_types import HotRecord
from src.select_topics import select_topics


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_cached_records(path) -> list[HotRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []

    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            records.append(
                HotRecord(
                    platform=str(item["platform"]),
                    rank=int(item["rank"]),
                    title=str(item["title"]),
                    hot=str(item.get("hot", "")),
                    url=str(item.get("url", "")),
                    crawl_time=str(item.get("crawl_time", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return records


def print_fetch_issues(issues) -> None:
    if not issues:
        return
    print("DailyHot fetch issues:")
    for issue in issues[:12]:
        print(f"- {issue.platform}: {issue.url} -> {issue.error}")
    if len(issues) > 12:
        print(f"- ... {len(issues) - 12} more issues")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    records, fetch_issues = fetch_all_platforms(PLATFORMS, return_issues=True)
    used_cache = False

    if not records:
        cached_records = read_cached_records(HOT_LIST_PATH)
        if cached_records:
            records = cached_records
            used_cache = True
        else:
            print_fetch_issues(fetch_issues)
            print("Collected records: 0")
            print("No cached records available; existing reports were left unchanged.")
            print("Set DAILY_HOT_API_BASE=http://localhost:6688 after starting a self-hosted DailyHotApi.")
            return

    selected = select_topics(
        records,
        min_count=MIN_SELECTED_TOPICS,
        max_count=MAX_SELECTED_TOPICS,
    )
    sources = enrich_topics(selected)
    cards = build_cards(selected, sources)

    cards_markdown = render_topic_cards(cards)
    digest_markdown = render_daily_digest(cards)
    digest_html = render_static_html(digest_markdown)

    write_json(HOT_LIST_PATH, [record.to_dict() for record in records])
    write_json(SELECTED_TOPICS_PATH, [topic.to_dict() for topic in selected])
    write_json(TOPIC_SOURCES_PATH, [source.to_dict() for source in sources])
    write_text(HOT_TOPIC_CARDS_PATH, cards_markdown)
    write_text(DAILY_DIGEST_PATH, digest_markdown)
    write_text(DAILY_DIGEST_HTML_PATH, digest_html)

    print_fetch_issues(fetch_issues)
    print(f"Collected records: {len(records)}")
    if used_cache:
        print(f"Source: cached {HOT_LIST_PATH}")
    print(f"Selected topics: {len(selected)}")
    print(f"Cards: {len(cards)}")
    print(f"Digest: {DAILY_DIGEST_PATH}")
    print(f"HTML: {DAILY_DIGEST_HTML_PATH}")


if __name__ == "__main__":
    main()
