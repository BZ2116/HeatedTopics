import argparse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.core_pipeline.dailyhot_client import collect_dailyhot_records, fetch_dailyhot_route
from src.core_pipeline.detail_collector import collect_topic_details, html_to_text
from src.core_pipeline.json_store import read_json_list, write_json_list
from src.core_pipeline.providers.baidu import collect_baidu_detail
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.recent_topics import collection_window_days, deduplicate_hot_records
from src.core_pipeline.report_renderer import render_markdown_report, render_recent_hot_topics_report
from src.core_pipeline.session_gate import check_required_sessions
from src.core_pipeline.source_registry import ALL_DAILYHOT_ROUTES
from src.core_pipeline.types import DetailEvidence, HotRecord, TopicBrief


def now_shanghai_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def output_paths() -> dict[str, Path]:
    return {
        "hot_records": Path("data/raw/dailyhot_records.json"),
        "detail_evidence": Path("data/evidence/detail_evidence.json"),
        "topic_clusters": Path("data/processed/topic_clusters.json"),
        "topic_briefs": Path("data/processed/topic_briefs.json"),
        "markdown_report": Path("reports/core_platform_topic_digest.md"),
    }


def default_search_provider(query: str) -> list[dict[str, str]]:
    return []


def fetch_url_text(url: str, timeout_seconds: int = 15) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "heatedTopics/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
    return html_to_text(body)


def rooted_output_paths(root: Path) -> dict[str, Path]:
    return {key: root / value for key, value in output_paths().items()} | {
        "recent_markdown_report": root / "reports/recent_hot_topics_digest.md"
    }


def run_recent_detail_collection(
    window: str,
    root: Path = Path("."),
    routes: tuple[str, ...] = ALL_DAILYHOT_ROUTES,
    route_fetcher=None,
    search_provider=default_search_provider,
    page_fetcher=fetch_url_text,
    session_status: dict[str, str] | None = None,
    now=now_shanghai_iso,
) -> dict[str, int]:
    collection_window_days(window)
    captured_at = now()
    if route_fetcher is None:
        route_fetcher = lambda route: fetch_dailyhot_route("https://dailyhotapi.now.sh", route)
    records = collect_dailyhot_records(routes=routes, captured_at=captured_at, fetcher=route_fetcher)
    topics = deduplicate_hot_records([record for record in records if record.fetch_status == "ok"])
    status = session_status if session_status is not None else check_required_sessions()
    evidence_rows = collect_topic_details(
        topics=topics,
        fetched_at=captured_at,
        search_provider=search_provider,
        session_status=status,
        page_fetcher=page_fetcher,
    )
    paths = rooted_output_paths(root)
    write_json_list(paths["hot_records"], [record.to_dict() for record in records])
    serializable_topics = [
        {
            "topic_key": topic["topic_key"],
            "canonical_title": topic["canonical_title"],
            "hot_record_ids": topic["hot_record_ids"],
            "platforms": topic["platforms"],
            "best_rank": topic["best_rank"],
        }
        for topic in topics
    ]
    write_json_list(paths["topic_clusters"], serializable_topics)
    write_json_list(paths["detail_evidence"], [row.to_dict() for row in evidence_rows])
    report = render_recent_hot_topics_report(
        topics=topics,
        evidence_rows=evidence_rows,
        generated_at=captured_at,
        window=window,
    )
    paths["recent_markdown_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["recent_markdown_report"].write_text(report, encoding="utf-8")
    return {
        "hot_records_count": len(records),
        "topics_count": len(topics),
        "detail_evidence_count": len(evidence_rows),
    }


def render_report_command() -> None:
    paths = output_paths()
    rows = read_json_list(paths["topic_briefs"])
    briefs = [TopicBrief(**row) for row in rows]
    markdown = render_markdown_report(briefs, generated_at=now_shanghai_iso())
    paths["markdown_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["markdown_report"].write_text(markdown, encoding="utf-8")


def collect_core_details_command() -> None:
    paths = output_paths()
    records = [HotRecord(**row) for row in read_json_list(paths["hot_records"])]
    session_status = check_required_sessions()
    fetched_at = now_shanghai_iso()

    evidence_list: list[DetailEvidence] = []
    for record in records:
        weibo_ev = collect_weibo_detail(record, fetched_at, session_status["weibo"], [])
        evidence_list.append(weibo_ev)

        xiaohongshu_ev = collect_xiaohongshu_detail(record, fetched_at, session_status["xiaohongshu"], [])
        evidence_list.append(xiaohongshu_ev)

        baidu_ev = collect_baidu_detail(record, fetched_at, [])
        evidence_list.append(baidu_ev)

    paths["detail_evidence"].parent.mkdir(parents=True, exist_ok=True)
    write_json_list(paths["detail_evidence"], [ev.to_dict() for ev in evidence_list])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("paths", "render-report", "collect-core-details", "collect-recent-details"))
    parser.add_argument("--window", choices=("today", "last_7_days"), default="today")
    args = parser.parse_args()
    if args.command == "paths":
        write_json_list("data/processed/pipeline_paths.json", [{key: str(value) for key, value in output_paths().items()}])
    if args.command == "render-report":
        render_report_command()
    if args.command == "collect-core-details":
        collect_core_details_command()
    if args.command == "collect-recent-details":
        run_recent_detail_collection(window=args.window)


if __name__ == "__main__":
    main()
