import argparse
import inspect
import json
import sys
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from src.core_pipeline.cache_store import CacheStore
from src.core_pipeline.creator_topic_classifier import build_creator_topic_index
from src.core_pipeline.dailyhot_client import collect_dailyhot_records, fetch_dailyhot_route
from src.core_pipeline.browser_detail_fetcher import fetch_social_details_with_browser
from src.core_pipeline.detail_collector import collect_topic_details, html_to_text
from src.core_pipeline.json_store import read_json_list, read_jsonl, write_json_list, write_jsonl
from src.core_pipeline.providers.baidu import collect_baidu_detail, search_baidu_details
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.weibo_hot import fetch_weibo_hot_records_with_browser
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.providers.xiaohongshu_hot import fetch_xiaohongshu_hot_records
from src.core_pipeline.recent_topics import collection_window_days, deduplicate_hot_records
from src.core_pipeline.report_renderer import (
    render_creator_topic_cards,
    render_markdown_report,
    render_recent_hot_topics_report,
)
from src.core_pipeline.session_gate import check_required_sessions
from src.core_pipeline.source_registry import ALL_DAILYHOT_ROUTES, DETAIL_ENABLED_PLATFORMS
from src.core_pipeline.topic_summary import load_manual_summaries
from src.core_pipeline.types import DetailEvidence, HotRecord, TopicBrief


CORE_HOT_DETAIL_PLATFORMS = ("baidu", "weibo", "xiaohongshu")
PLATFORM_RAW_OUTPUTS = {
    "xiaohongshu_topics": "xiaohongshu_topics.jsonl",
    "xiaohongshu_notes": "xiaohongshu_notes.jsonl",
    "baidu_topics": "baidu_topics.jsonl",
    "baidu_details": "baidu_details.jsonl",
    "weibo_topics": "weibo_topics.jsonl",
    "weibo_posts": "weibo_posts.jsonl",
}


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
        "creator_topic_index": Path("data/processed/creator_topic_index.json"),
        "creator_topic_cards": Path("reports/creator_topic_cards.md"),
    }


def default_search_provider(query: str) -> list[dict[str, str]]:
    return search_baidu_details(query)


def default_social_detail_fetcher(platform: str, query: str) -> dict[str, object]:
    if platform == "xiaohongshu":
        return fetch_social_details_with_browser(platform, query, max_items=20)
    return fetch_social_details_with_browser(platform, query)


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


def platform_raw_paths(root: Path = Path(".")) -> dict[str, Path]:
    raw_dir = root / "data/raw/platforms"
    return {key: raw_dir / filename for key, filename in PLATFORM_RAW_OUTPUTS.items()}


def raw_detail_rows(evidence_rows: list[DetailEvidence], records: list[HotRecord]) -> list[dict[str, Any]]:
    records_by_id = {record.id: record for record in records}
    rows = []
    for evidence in evidence_rows:
        record = _record_for_evidence(evidence, records_by_id)
        rows.append(
            {
                "source": evidence.platform,
                "url": _raw_detail_url(evidence, record),
                "title": record.title if record is not None else evidence.query or evidence.title,
                "content": _raw_detail_content(evidence),
                "cover": record.cover if record is not None else "",
                "hotvalue": record.hot_value if record is not None else str(evidence.metrics.get("hot_value", "")),
                "rank": record.rank if record is not None else evidence.metrics.get("rank", ""),
            }
        )
    return rows


def _record_for_evidence(evidence: DetailEvidence, records_by_id: dict[str, HotRecord]) -> HotRecord | None:
    for record_id in evidence.related_hot_record_ids:
        record = records_by_id.get(record_id)
        if record is not None:
            return record
    return None


def _raw_detail_url(evidence: DetailEvidence, record: HotRecord | None) -> str:
    for url in evidence.result_urls:
        if url:
            return url
    if evidence.url:
        return evidence.url
    if record is None:
        return ""
    return record.url or record.mobile_url


def _raw_detail_content(evidence: DetailEvidence) -> str:
    raw_payload = evidence.raw_payload
    raw_page_text = raw_payload.get("raw_page_text")
    if isinstance(raw_page_text, str) and raw_page_text:
        return raw_page_text
    browser_raw = raw_payload.get("browser_raw")
    if isinstance(browser_raw, dict):
        page_text = browser_raw.get("page_text")
        if isinstance(page_text, str) and page_text:
            return page_text
    content_pages = raw_payload.get("content_pages")
    if isinstance(content_pages, list) and content_pages:
        return _join_raw_result_rows(content_pages)
    search_results = raw_payload.get("search_results")
    if isinstance(search_results, list) and search_results:
        return _join_raw_result_rows(search_results)
    for key in ("posts", "notes"):
        rows = raw_payload.get(key)
        if isinstance(rows, list) and rows:
            return _join_raw_result_rows(rows)
    return evidence.content


def _join_raw_result_rows(rows: list[object]) -> str:
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_parts = [
            str(row.get("title", "")).strip(),
            str(row.get("content", "")).strip(),
            str(row.get("snippet", "")).strip(),
            str(row.get("url", "")).strip(),
        ]
        parts.append("\n".join(part for part in row_parts if part))
    return "\n\n".join(part for part in parts if part)


def write_platform_raw_outputs(root: Path, records: list[HotRecord], evidence_rows: list[DetailEvidence]) -> None:
    paths = platform_raw_paths(root)
    for platform, detail_key in (
        ("xiaohongshu", "notes"),
        ("baidu", "details"),
        ("weibo", "posts"),
    ):
        write_jsonl(paths[f"{platform}_topics"], platform_topic_raw_rows(records, platform))
        write_jsonl(paths[f"{platform}_{detail_key}"], platform_detail_raw_rows(evidence_rows, records, platform))


def platform_topic_raw_rows(records: list[HotRecord], platform: str) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if record.platform != platform:
            continue
        rows.append(
            {
                "platform": platform,
                "kind": "topic",
                "topic": record.title,
                "title": record.title,
                "hot_value": record.hot_value,
                "rank": record.rank,
                "url": record.url or record.mobile_url,
                "captured_at": record.captured_at,
                "source": record.source,
                "fetch_status": record.fetch_status,
                "error_type": record.error_type,
                "record": record.to_dict(),
                "raw_payload": record.raw_payload,
            }
        )
    return rows


def platform_detail_raw_rows(
    evidence_rows: list[DetailEvidence],
    records: list[HotRecord],
    platform: str,
) -> list[dict[str, Any]]:
    records_by_id = {record.id: record for record in records}
    rows = []
    for evidence in evidence_rows:
        if evidence.platform != platform:
            continue
        record = _record_for_evidence(evidence, records_by_id)
        row = {
            "platform": platform,
            "kind": _platform_detail_kind(platform),
            "topic_key": evidence.topic_key,
            "query": evidence.query,
            "title": evidence.title,
            "url": _raw_detail_url(evidence, record),
            "fetched_at": evidence.fetched_at,
            "fetch_status": evidence.fetch_status,
            "error_type": evidence.error_type,
            "metrics": evidence.metrics,
            "comments_preview": evidence.comments_preview,
            "result_urls": evidence.result_urls,
            "hot_record": record.to_dict() if record is not None else None,
            "evidence": evidence.to_dict(),
            "raw_payload": evidence.raw_payload,
        }
        row.update(_platform_specific_raw_fields(platform, evidence.raw_payload))
        rows.append(row)
    return rows


def _platform_detail_kind(platform: str) -> str:
    return {
        "xiaohongshu": "notes",
        "baidu": "details",
        "weibo": "posts",
    }.get(platform, "details")


def _platform_specific_raw_fields(platform: str, raw_payload: dict[str, Any]) -> dict[str, Any]:
    browser_raw = raw_payload.get("browser_raw")
    fields: dict[str, Any] = {}
    if isinstance(browser_raw, dict):
        fields["browser_raw"] = browser_raw
    if platform == "xiaohongshu":
        fields["notes"] = raw_payload.get("notes", []) if isinstance(raw_payload.get("notes"), list) else []
        fields["external_detail_status"] = str(raw_payload.get("external_detail_status", ""))
        fields["external_detail_source"] = str(raw_payload.get("external_detail_source", ""))
        fields["placeholder_reason"] = str(raw_payload.get("placeholder_reason", ""))
    elif platform == "weibo":
        fields["posts"] = raw_payload.get("posts", []) if isinstance(raw_payload.get("posts"), list) else []
    elif platform == "baidu":
        fields["search_results"] = raw_payload.get("search_results", []) if isinstance(raw_payload.get("search_results"), list) else []
        fields["content_pages"] = raw_payload.get("content_pages", []) if isinstance(raw_payload.get("content_pages"), list) else []
        fields["query_attempts"] = raw_payload.get("query_attempts", []) if isinstance(raw_payload.get("query_attempts"), list) else []
    return fields


ProgressReporter = Callable[[int, int, str], None]


def report_progress(progress: ProgressReporter | None, current: int, total: int, message: str) -> None:
    if progress is not None:
        progress(current, total, message)


def print_progress(current: int, total: int, message: str) -> None:
    line = f"[{current}/{total}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_line = line.encode(encoding, errors="replace").decode(encoding)
        print(safe_line)


def missing_browser_sessions(status: dict[str, str]) -> list[str]:
    return [platform for platform in ("weibo", "xiaohongshu") if status.get(platform) != "ok"]


def missing_session_message(missing: list[str]) -> str:
    if not missing:
        return ""
    commands = "; ".join(f"uv run python -m src.browser.session_manager login {platform}" for platform in missing)
    return f"未登录平台将跳过详情采集：{', '.join(missing)}；可执行：{commands}"


def has_ok_platform_record(records: list[HotRecord], platform: str) -> bool:
    return any(record.platform == platform and record.fetch_status == "ok" for record in records)


def limit_hot_records_per_platform(records: list[HotRecord], max_per_platform: int | None) -> list[HotRecord]:
    if max_per_platform is None:
        return records
    if max_per_platform < 1:
        raise ValueError("max_per_platform must be positive")
    counts: dict[str, int] = {}
    limited: list[HotRecord] = []
    for record in records:
        if record.fetch_status != "ok":
            limited.append(record)
            continue
        count = counts.get(record.platform, 0)
        if count >= max_per_platform:
            continue
        counts[record.platform] = count + 1
        limited.append(record)
    return limited


def replace_failed_platform_records(records: list[HotRecord], platform: str, replacement: list[HotRecord]) -> list[HotRecord]:
    if not replacement:
        return records
    return [record for record in records if not (record.platform == platform and record.fetch_status != "ok")] + replacement


def cached_xiaohongshu_hot_records(
    captured_at: str,
    cache_window: str,
    cache_store,
    fetcher: Callable[[str], list[HotRecord]],
    max_items: int = 20,
) -> list[HotRecord]:
    cache_key = f"hot:xiaohongshu:{cache_window}:{max_items}"
    cached_rows = cache_store.read(cache_key) if cache_store is not None else None
    if cached_rows is not None:
        return [HotRecord(**row["record"]) for row in cached_rows if isinstance(row, dict) and "record" in row]
    records = _call_hot_fetcher(fetcher, captured_at, max_items)
    if cache_store is not None:
        cache_store.write(cache_key, [{"record": record.to_dict()} for record in records], fetched_at=captured_at)
    return records


def cached_weibo_hot_records(
    captured_at: str,
    cache_window: str,
    cache_store,
    fetcher: Callable[..., list[HotRecord]],
    max_items: int = 50,
) -> list[HotRecord]:
    cache_key = f"hot:weibo:{cache_window}:{max_items}"
    cached_rows = cache_store.read(cache_key) if cache_store is not None else None
    if cached_rows is not None:
        return [HotRecord(**row["record"]) for row in cached_rows if isinstance(row, dict) and "record" in row]
    records = _call_hot_fetcher(fetcher, captured_at, max_items)
    if cache_store is not None:
        cache_store.write(cache_key, [{"record": record.to_dict()} for record in records], fetched_at=captured_at)
    return records


def _call_hot_fetcher(
    fetcher: Callable[..., list[HotRecord]],
    captured_at: str,
    max_items: int,
) -> list[HotRecord]:
    signature = inspect.signature(fetcher)
    if "max_items" in signature.parameters:
        return fetcher(captured_at, max_items=max_items)
    return fetcher(captured_at)


def run_recent_detail_collection(
    window: str,
    root: Path = Path("."),
    routes: tuple[str, ...] = ALL_DAILYHOT_ROUTES,
    route_fetcher: Callable[[str], dict[str, Any]] | None = None,
    search_provider=default_search_provider,
    page_fetcher=fetch_url_text,
    session_status: dict[str, str] | None = None,
    social_detail_fetcher=default_social_detail_fetcher,
    now=now_shanghai_iso,
    progress: ProgressReporter | None = None,
    cache_store=None,
    refresh: bool = False,
    detail_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS,
    supplemental_social_platforms: tuple[str, ...] = (),
    xiaohongshu_hot_fetcher: Callable[..., list[HotRecord]] = fetch_xiaohongshu_hot_records,
    weibo_hot_fetcher: Callable[..., list[HotRecord]] = fetch_weibo_hot_records_with_browser,
    max_hot_per_platform: int | None = None,
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
    records = limit_hot_records_per_platform(records, max_hot_per_platform)
    report_progress(progress, 3, total_steps, f"去重生成话题：{len(records)} 条热榜记录")
    topics = deduplicate_hot_records([record for record in records if record.fetch_status == "ok"])
    report_progress(progress, 4, total_steps, "检查登录态")
    status = session_status if session_status is not None else check_required_sessions()
    missing_sessions = missing_browser_sessions(status)
    if missing_sessions:
        report_progress(progress, 4, total_steps, missing_session_message(missing_sessions))
    if "xiaohongshu" in routes and not has_ok_platform_record(records, "xiaohongshu"):
        try:
            xiaohongshu_records = cached_xiaohongshu_hot_records(
                captured_at,
                window,
                cache_store,
                xiaohongshu_hot_fetcher,
                max_items=max_hot_per_platform or 20,
            )
            records = replace_failed_platform_records(records, "xiaohongshu", xiaohongshu_records)
            records = limit_hot_records_per_platform(records, max_hot_per_platform)
            if xiaohongshu_records:
                report_progress(progress, 4, total_steps, f"小红书 DailyHot 无数据，已从外部热榜补采 {len(xiaohongshu_records)} 条")
        except Exception as exc:
            report_progress(progress, 4, total_steps, f"小红书网页热点补采失败：{type(exc).__name__}")
    if "weibo" in routes and not has_ok_platform_record(records, "weibo") and status.get("weibo") == "ok":
        try:
            weibo_records = cached_weibo_hot_records(
                captured_at,
                window,
                cache_store,
                weibo_hot_fetcher,
                max_items=max_hot_per_platform or 50,
            )
            records = replace_failed_platform_records(records, "weibo", weibo_records)
            records = limit_hot_records_per_platform(records, max_hot_per_platform)
            if weibo_records:
                report_progress(progress, 4, total_steps, f"微博 DailyHot 无数据，已从登录态热搜页补采 {len(weibo_records)} 条")
        except Exception as exc:
            report_progress(progress, 4, total_steps, f"微博热搜页补采失败：{type(exc).__name__}")
    topics = deduplicate_hot_records([record for record in records if record.fetch_status == "ok"])
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
        supplemental_social_platforms=supplemental_social_platforms,
        progress=lambda current, total, message: report_progress(progress, 5, total_steps, message),
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
    write_jsonl(paths["raw_detail_evidence"], raw_detail_rows(evidence_rows, records))
    write_platform_raw_outputs(root, records, evidence_rows)
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
    write_jsonl(paths["raw_detail_evidence"], raw_detail_rows(evidence_list, records))
    write_platform_raw_outputs(Path("."), records, evidence_list)


def build_creator_topic_index_command(
    root: Path = Path("."),
    generated_at: str | None = None,
    render_report: bool = False,
    manual_summaries_path: Path | None = None,
    summary_mode: str = "rule",
) -> dict[str, int]:
    paths = rooted_output_paths(root)
    generated = generated_at or now_shanghai_iso()
    hot_records_path = paths["hot_records"]
    raw_detail_path = paths["raw_detail_evidence"]
    topic_clusters_path = paths["topic_clusters"]
    records = read_json_list(hot_records_path)
    detail_rows = read_jsonl(raw_detail_path)
    topics = read_json_list(topic_clusters_path)
    missing_inputs = [
        (label, str(path))
        for label, path, rows in (
            ("热榜记录", hot_records_path, records),
            ("详情证据 JSONL", raw_detail_path, detail_rows),
            ("话题聚类", topic_clusters_path, topics),
        )
        if not rows and not path.exists()
    ]
    if missing_inputs:
        print("[警告] 以下输入文件不存在，将生成空索引：", file=sys.stderr)
        for label, path in missing_inputs:
            print(f"  - {label}: {path}", file=sys.stderr)
        print(
            "请先在项目根目录运行采集命令：uv run python -m src.core_pipeline.run collect-recent-details --window today",
            file=sys.stderr,
        )
    manual_summaries = load_manual_summaries(manual_summaries_path) if manual_summaries_path is not None else {}
    if summary_mode == "model":
        print("[提示] model summary mode is reserved; using rule/manual summaries in this build.", file=sys.stderr)
    index = build_creator_topic_index(
        topics=topics,
        hot_records=records,
        detail_rows=detail_rows,
        generated_at=generated,
        source_files=[
            hot_records_path.as_posix(),
            raw_detail_path.as_posix(),
            topic_clusters_path.as_posix(),
        ],
        manual_summaries=manual_summaries,
        model_summaries={},
    )
    paths["creator_topic_index"].parent.mkdir(parents=True, exist_ok=True)
    paths["creator_topic_index"].write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if render_report:
        report = render_creator_topic_cards(index)
        paths["creator_topic_cards"].parent.mkdir(parents=True, exist_ok=True)
        paths["creator_topic_cards"].write_text(report, encoding="utf-8")
    print(f"生成创作者索引：{len(index['topics'])} 个话题")
    print(f"  索引文件：{paths['creator_topic_index'].resolve()}")
    if render_report:
        print(f"  卡片报告：{paths['creator_topic_cards'].resolve()}")
    return {"topics_count": len(index["topics"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("paths", "render-report", "collect-core-details", "collect-recent-details", "collect-core-hot-details", "build-creator-topic-index"),
    )
    parser.add_argument("--window", choices=("today", "last_7_days"), default="today")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--detail-platforms", default="")
    parser.add_argument("--max-hot-per-platform", type=int, default=10)
    parser.add_argument("--render-report", action="store_true")
    parser.add_argument("--manual-summaries", default="")
    parser.add_argument("--summary-mode", choices=("rule", "model"), default="rule")
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
            max_hot_per_platform=args.max_hot_per_platform,
        )
    if args.command == "collect-core-hot-details":
        run_recent_detail_collection(
            window=args.window,
            routes=CORE_HOT_DETAIL_PLATFORMS,
            progress=print_progress,
            refresh=args.refresh,
            detail_platforms=CORE_HOT_DETAIL_PLATFORMS,
            supplemental_social_platforms=("weibo", "xiaohongshu"),
            max_hot_per_platform=args.max_hot_per_platform,
        )
    if args.command == "build-creator-topic-index":
        manual_summaries_path = Path(args.manual_summaries) if args.manual_summaries else None
        build_creator_topic_index_command(
            root=Path("."),
            render_report=args.render_report,
            manual_summaries_path=manual_summaries_path,
            summary_mode=args.summary_mode,
        )


if __name__ == "__main__":
    main()
