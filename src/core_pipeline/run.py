import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.core_pipeline.json_store import read_json_list, write_json_list
from src.core_pipeline.providers.baidu import collect_baidu_detail
from src.core_pipeline.providers.weibo import collect_weibo_detail
from src.core_pipeline.providers.xiaohongshu import collect_xiaohongshu_detail
from src.core_pipeline.report_renderer import render_markdown_report
from src.core_pipeline.session_gate import check_required_sessions
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
    parser.add_argument("command", choices=("paths", "render-report", "collect-core-details"))
    args = parser.parse_args()
    if args.command == "paths":
        write_json_list("data/processed/pipeline_paths.json", [{key: str(value) for key, value in output_paths().items()}])
    if args.command == "render-report":
        render_report_command()
    if args.command == "collect-core-details":
        collect_core_details_command()


if __name__ == "__main__":
    main()