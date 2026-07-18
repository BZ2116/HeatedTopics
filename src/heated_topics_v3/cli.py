import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from heated_topics_v3.fetcher_factory import make_search_fetcher
from heated_topics_v3.hot_board_cache import utc8_today
from heated_topics_v3.llm_client import call_llm, load_llm_config
from heated_topics_v3.llm_keywords import KEYWORD_EXTRACTION_SYSTEM, extract_persona_keywords
from heated_topics_v3.pipeline import (
    run_juejin_pipeline,
    run_toutiao_pipeline,
    run_toutiao_pipeline_v2,
)
from heated_topics_v3.profile_loader import load_persona_profile
from heated_topics_v3.quota import (
    QuotaExceededError,
    check_quota,
    commit_quota,
    load_quota,
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

    refresh_kw = subparsers.add_parser("refresh-keywords", help="Delete keyword cache for one or all users, forcing LLM re-extraction on next run.")
    _add_refresh_keywords_args(refresh_kw)

    subparsers.add_parser("check-llm", help="Test the configured LLM without reading or writing response cache.")

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
            custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())
            today = utc8_today()
            on_search_committed = None
            if not args.skip_quota:
                user_id = load_persona_profile(args.profile_v2).user_id
                state = load_quota(args.state_root, user_id, today)
                try:
                    check_quota(state, args.max_quota_per_day)
                except QuotaExceededError as exc:
                    print(str(exc), file=sys.stderr)
                    raise SystemExit(2) from exc
                on_search_committed = lambda: commit_quota(args.state_root, user_id, today)
            # Build fetcher with cookie from project root
            cookie_path = Path(__file__).resolve().parent.parent / ".toutiao_cookie"
            log_path = Path(__file__).resolve().parent.parent / ".fetcher_log.json"
            fetcher = make_search_fetcher(
                cookie_path=cookie_path,
                log_path=log_path,
                timeout=30,
            )
            result = run_toutiao_pipeline_v2(
                profile_path=args.profile_v2,
                output_root=args.output_root,
                fetched_at=fetched_at,
                hot_board_cache_root=args.cache_root,
                persona_keyword_cache_root=args.cache_root / "core_keywords",
                llm_cache_root=args.cache_root / "llm",
                use_llm_keywords=use_llm_keywords,
                use_llm_summary=use_llm_summary,
                force_hot_board_refresh=args.force_hot_board_refresh,
                offline=args.offline,
                top_n=args.top_n,
                custom_keywords=custom_keywords,
                on_search_committed=on_search_committed,
                fetcher=fetcher,
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
    if args.command == "refresh-keywords":
        _handle_refresh_keywords(args)
    if args.command == "check-llm":
        _handle_check_llm()


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
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--force-hot-board-refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--custom-keyword", dest="custom_keyword", action="append", default=[])
    parser.add_argument("--state-root", default=Path("state"), type=Path)
    parser.add_argument("--max-quota-per-day", dest="max_quota_per_day", default=3, type=int)
    parser.add_argument("--skip-quota", dest="skip_quota", action="store_true")


def _add_refresh_keywords_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", type=Path, required=True, help="Path to a profile (e.g. config/profiles/qiongyou_001.json)")
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--write", action="store_true", help="Write LLM-generated keywords back to the profile JSON file (replaces core_keywords)")


def _handle_refresh_keywords(args) -> None:
    cache_dir = args.cache_root / "core_keywords"
    profile = load_persona_profile(args.profile)
    profile_path = Path(args.profile).resolve()

    # Extract keywords via LLM (bypass cache by deleting first)
    cache_file = cache_dir / f"{profile.user_id}.json"
    if cache_file.exists():
        cache_file.unlink()

    extraction = extract_persona_keywords(
        profile,
        cache_dir=cache_dir,
        use_cache=False,
        llm=lambda prompt, system, **kw: call_llm(prompt, system=system, **kw),
        allow_llm=True,
    )

    new_keywords = [k.keyword for k in extraction.keywords]
    print(f"Generated {len(new_keywords)} keywords:")
    for k in new_keywords:
        print(f"  - {k}")

    if args.write:
        # Read original profile, replace core_keywords, write back
        payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        payload["core_keywords"] = new_keywords
        profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Written to {profile_path}")


def _handle_check_llm() -> None:
    config = load_llm_config()
    text = call_llm(
        "Reply with exactly OK.",
        system="You are a connectivity checker.",
        max_tokens=16,
        temperature=0.1,
        use_cache=False,
    )
    print(f"LLM connection: {text.strip()}")
    print(f"model: {config.model}")
    print(f"base_url: {config.base_url}")


def _add_platform_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--fetched-at", default=None)


if __name__ == "__main__":
    main()
