import argparse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from src.core_pipeline.cache_store import CacheStore
from src.core_pipeline.dailyhot_client import collect_dailyhot_records, fetch_dailyhot_route
from src.core_pipeline.browser_detail_fetcher import fetch_social_details_with_browser
from src.core_pipeline.detail_collector import collect_topic_details, html_to_text
from src.core_pipeline.json_store import read_json_list, write_json_list, write_jsonl
from src.core_pipeline.providers.baidu import collect_baidu_detail, search_baidu_details
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.recent_topics import collection_window_days, deduplicate_hot_records
from src.core_pipeline.report_renderer import render_markdown_report, render_recent_hot_topics_report
from src.core_pipeline.session_gate import check_required_sessions
from src.core_pipeline.source_registry import ALL_DAILYHOT_ROUTES, DETAIL_ENABLED_PLATFORMS
from src.core_pipeline.types import DetailEvidence, HotRecord, TopicBrief


def now_shanghai_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def output_paths() -> dict[str, Path]:
    return {
        "hot_records": Path("data/raw/dailyhot_records.json"),
        "detail_evidence": Path("data/evidence/detail_evidence.json"),
        "raw_detail_evidence": Path("data/evidence/detail_evidence_raw.jsonl"),
        "topic_clusters": Path("data/processed/topic_clusters.json"),
        "topic_briefs": Path("data/processed/topic_briefs.json"),
        "markdown_report": Path("reports/core_platform_topic_digest.md"),
    }


def default_search_provider(query: str) -> list[dict[str, str]]:
    return search_baidu_details(query)


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


ProgressReporter = Callable[[int, int, str], None]


def report_progress(progress: ProgressReporter | None, current: int, total: int, message: str) -> None:
    if progress is not None:
        progress(current, total, message)


def print_progress(current: int, total: int, message: str) -> None:
    print(f"[{current}/{total}] {message}")


def missing_browser_sessions(status: dict[str, str]) -> list[str]:
    return [platform for platform in ("weibo", "xiaohongshu") if status.get(platform) != "ok"]


def missing_session_message(missing: list[str]) -> str:
    if not missing:
        return ""
    commands = "; ".join(f"uv run python -m src.browser.session_manager login {platform}" for platform in missing)
    return f"未登录平台将跳过详情采集：{', '.join(missing)}；可执行：{commands}"


def run_recent_detail_collection(
    window: str,
    root: Path = Path("."),
    routes: tuple[str, ...] = ALL_DAILYHOT_ROUTES,
    route_fetcher: Callable[[str], dict[str, Any]] | None = None,
    search_provider=default_search_provider,
    page_fetcher=fetch_url_text,
    session_status: dict[str, str] | None = None,
    social_detail_fetcher=fetch_social_details_with_browser,
    now=now_shanghai_iso,
    progress: ProgressReporter | None = None,
    cache_store=None,
    refresh: bool = False,
    detail_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS,
) -> dict[str, int]:
    if cache_store is None:
        cache_store = CacheStore(root / "data/cache", refresh=refresh)
    total_steps = 8
    report_progress(progress, 1, total_steps, "校验采集窗口")
    collection_window_days(window)
    captured_at = now()
    if route_fetcher is None:
        route_fetcher = lambda route: fetch_dailyhot_route("https://dailyhotapi.now.sh", route)
    report_progress(progress, 2, total_steps, f"采集热榜：{', '.join(routes)}")
    records = collect_dailyhot_records(
        routes=routes,
        captured_at=captured_at,
        fetcher=route_fetcher,
        cache_store=cache_store,
        cache_window=window,
    )
    report_progress(progress, 3, total_steps, f"去重生成话题：{len(records)} 条热榜记录")
    topics = deduplicate_hot_records([record for record in records if record.fetch_status == "ok"])
    report_progress(progress, 4, total_steps, "检查登录态")
    status = session_status if session_status is not None else check_required_sessions()
    missing_sessions = missing_browser_sessions(status)
    if missing_sessions:
        report_progress(progress, 4, total_steps, missing_session_message(missing_sessions))
    report_progress(progress, 5, total_steps, f"采集详情证据：{len(topics)} 个话题")
    evidence_rows = collect_topic_details(
        topics=topics,
        fetched_at=captured_at,
        search_provider=search_provider,
        session_status=status,
        page_fetcher=page_fetcher,
        social_detail_fetcher=social_detail_fetcher,
        cache_store=cache_store,
        enabled_detail_platforms=detail_platforms,
    )
    report_progress(progress, 6, total_steps, "写入 JSON / JSONL")
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
    write_jsonl(paths["raw_detail_evidence"], [row.to_dict() for row in evidence_rows])
    report_progress(progress, 7, total_steps, "生成 Markdown 报告")
    report = render_recent_hot_topics_report(
        topics=topics,
        evidence_rows=evidence_rows,
        generated_at=captured_at,
        window=window,
    )
    paths["recent_markdown_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["recent_markdown_report"].write_text(report, encoding="utf-8")
    report_progress(
        progress,
        8,
        total_steps,
        f"完成：{len(records)} 条热榜记录，{len(topics)} 个话题，{len(evidence_rows)} 条详情证据",
    )
    return {
        "hot_records_count": len(records),
        "topics_count": len(topics),
        "detail_evidence_count": len(evidence_rows),
        "missing_browser_sessions_count": len(missing_sessions),
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
    write_jsonl(paths["raw_detail_evidence"], [ev.to_dict() for ev in evidence_list])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("paths", "render-report", "collect-core-details", "collect-recent-details"))
    parser.add_argument("--window", choices=("today", "last_7_days"), default="today")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--detail-platforms", default="")
    args = parser.parse_args()
    if args.command == "paths":
        write_json_list("data/processed/pipeline_paths.json", [{key: str(value) for key, value in output_paths().items()}])
    if args.command == "render-report":
        render_report_command()
    if args.command == "collect-core-details":
        collect_core_details_command()
    if args.command == "collect-recent-details":
        detail_platforms = tuple(part.strip() for part in args.detail_platforms.split(",") if part.strip()) or DETAIL_ENABLED_PLATFORMS
        run_recent_detail_collection(
            window=args.window,
            progress=print_progress,
            refresh=args.refresh,
            detail_platforms=detail_platforms,
        )


if __name__ == "__main__":
    main()
