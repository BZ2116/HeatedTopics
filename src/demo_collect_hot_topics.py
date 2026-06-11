import json

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
from src.select_topics import select_topics


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    records = fetch_all_platforms(PLATFORMS)
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

    print(f"Collected records: {len(records)}")
    print(f"Selected topics: {len(selected)}")
    print(f"Cards: {len(cards)}")
    print(f"Digest: {DAILY_DIGEST_PATH}")
    print(f"HTML: {DAILY_DIGEST_HTML_PATH}")


if __name__ == "__main__":
    main()