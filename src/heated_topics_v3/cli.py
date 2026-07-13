import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from heated_topics_v3.pipeline import (
    run_juejin_pipeline,
    run_toutiao_pipeline,
    run_toutiao_pipeline_v2,
)


def main() -> None:
    try:
        _main()
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run HeatedTopics V3 workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    juejin = subparsers.add_parser("juejin", help="Collect Juejin hot list and match it to a user profile.")
    _add_platform_args(juejin)

    toutiao = subparsers.add_parser("toutiao", help="Collect Toutiao hot list and match it to a user profile.")
    _add_toutiao_args(toutiao)

    args = parser.parse_args()
    if args.command == "juejin":
        fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        outputs = run_juejin_pipeline(
            profile_path=args.profile,
            output_root=args.output_root,
            fetched_at=fetched_at,
        )
        for name, path in outputs.items():
            print(f"{name}: {path}")
    if args.command == "toutiao":
        fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if args.profile_v2 is not None:
            use_llm_keywords = args.llm_keywords and not args.no_llm
            use_llm_summary = args.llm_summary and not args.no_llm
            use_llm_rerank = args.llm_rerank and not args.no_llm
            result = run_toutiao_pipeline_v2(
                profile_path=args.profile_v2,
                output_root=args.output_root,
                fetched_at=fetched_at,
                hot_board_cache_root=args.cache_root,
                persona_keyword_cache_root=args.cache_root / "core_keywords",
                llm_cache_root=args.cache_root / "llm",
                use_llm_keywords=use_llm_keywords,
                use_llm_summary=use_llm_summary,
                use_llm_rerank=use_llm_rerank,
                force_hot_board_refresh=args.force_hot_board_refresh,
                offline=args.offline,
                top_n=args.top_n,
            )
            print(f"run_dir: {result.run_dir}")
            print(f"report: {result.report_path}")
            print(f"focused: {result.focused_path}")
            print(f"candidates: {result.kept_total}/{result.candidates_total}")
            print(f"paths: {result.paths}")
            print(f"hot_board_source: {result.hot_board_source}")
            print(f"keyword_source: {result.keyword_source}")
        else:
            outputs = run_toutiao_pipeline(
                profile_path=args.profile,
                output_root=args.output_root,
                fetched_at=fetched_at,
            )
            for name, path in outputs.items():
                print(f"{name}: {path}")


def _add_toutiao_args(parser: argparse.ArgumentParser) -> None:
    profiles = parser.add_mutually_exclusive_group(required=True)
    profiles.add_argument("--profile", type=Path)
    profiles.add_argument("--profile-v2", type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--top-n", default=10, type=int)
    parser.add_argument("--llm-keywords", action="store_true")
    parser.add_argument("--llm-summary", action="store_true")
    parser.add_argument("--llm-rerank", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--force-hot-board-refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")


def _add_platform_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--fetched-at", default=None)


if __name__ == "__main__":
    main()
