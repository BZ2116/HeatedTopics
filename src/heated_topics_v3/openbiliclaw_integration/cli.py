"""CLI entry point for the openbiliclaw_integration recommender."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from heated_topics_v3.openbiliclaw_integration import output, recommender, runtime
from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError

logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI args. Raises SystemExit on parse errors."""
    p = argparse.ArgumentParser(
        prog="python -m heated_topics_v3.openbiliclaw_integration.cli",
        description="Multi-user hot-article recommender (V3 providers + OpenBiliClaw).",
    )
    p.add_argument("--users", required=True, help="Path to users.json")
    p.add_argument("--output", required=True, help="Path to write recommendations.json")
    p.add_argument("--limit", type=int, default=10, help="Top-N per user (default 10)")
    p.add_argument(
        "--max-parallel",
        type=int,
        default=5,
        help="Max concurrent users (default 5; 1 = serial)",
    )
    p.add_argument(
        "--providers",
        default=None,
        help="Comma-separated provider list (default: all)",
        type=lambda s: [x for x in s.split(",") if x],
    )
    p.add_argument(
        "--body-preview-chars",
        type=int,
        default=800,
        help="body_text_preview truncation length (default 800)",
    )
    p.add_argument(
        "--config",
        default="config/openbiliclaw.toml",
        help="OpenBiliClaw config path (default config/openbiliclaw.toml)",
    )
    p.add_argument(
        "--data-dir",
        default="data",
        help="Per-user data root (default data/)",
    )
    p.add_argument(
        "--per-user-timeout",
        type=float,
        default=180.0,
        help="Per-user timeout in seconds (default 180)",
    )
    p.add_argument(
        "--use-search",
        dest="use_search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Augment hot-list with provider.search() hits per user interest (default on)",
    )
    p.add_argument(
        "--prefer-search",
        dest="prefer_search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Trust search results over hot-list. Drops hot items that don't "
            "mention any user interest when search yields enough candidates "
            "(default on; pass --no-prefer-search to fall back to merge-only)"
        ),
    )
    p.add_argument(
        "--search-top-k",
        type=int,
        default=None,
        help="Top-K interests (by weight) to search; 0 disables search (default 3)",
    )
    p.add_argument(
        "--search-providers",
        default=None,
        help="Comma-separated override of providers used for search (default: toutiao,sina_news,thepaper,zhihu_daily)",
        type=lambda s: [x for x in s.split(",") if x],
    )
    p.add_argument(
        "--search-results-per-interest",
        type=int,
        default=5,
        help="Search results per (provider, interest) pair (default 5)",
    )
    p.add_argument(
        "--source",
        choices=("v3-hotlist", "last30days", "both"),
        default="v3-hotlist",
        help=(
            "Candidate source(s). 'v3-hotlist' uses HeatedTopics V3 providers "
            "(default). 'last30days' invokes the last30days CLI for 8 CN "
            "platforms. 'both' merges both pools and dedupes by URL."
        ),
    )
    p.add_argument(
        "--last30days-cli-path",
        default=None,
        help=(
            "Path to last30days's scripts/last30days.py "
            "(default: read from config/openbiliclaw.toml [last30days] cli_path)"
        ),
    )
    p.add_argument(
        "--last30days-query",
        default=None,
        help=(
            "Query passed to last30days CLI. If omitted, each user's "
            "primary_keyword or top-weighted interest is used."
        ),
    )
    p.add_argument(
        "--last30days-days",
        type=int,
        default=30,
        help="Days back for last30days (default 30)",
    )
    p.add_argument(
        "--last30days-no-fetch-bodies",
        dest="last30days_fetch_bodies",
        action="store_false",
        default=True,
        help="Disable --fetch-bodies on last30days (default: enabled)",
    )
    p.add_argument(
        "--last30days-timeout",
        type=float,
        default=120.0,
        help="Per-user last30days subprocess timeout in seconds (default 120)",
    )
    p.add_argument(
        "--last30days-save-dir",
        default=None,
        help="Base dir for last30days per-user output (default data/last30days)",
    )
    return p.parse_args(list(argv))


def _exit_code_for(results: list[dict[str, Any]]) -> int:
    if not results:
        return 0
    if any("error" in r for r in results):
        return 1
    return 0


def run_all_users_sync(**kwargs: Any) -> list[dict[str, Any]]:
    """Sync wrapper for tests. Real implementation calls asyncio.run."""
    return asyncio.run(recommender.run_all_users(**kwargs))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. Returns process exit code."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # Fail-fast checks
    runtime.verify_patch()
    missing = runtime.check_env()
    if missing:
        logger.error("Missing env vars: %s", ", ".join(missing))
        return 2

    users_path = Path(args.users)
    output_path = Path(args.output)
    try:
        specs = recommender.load_users(users_path)
    except (FileNotFoundError, json.JSONDecodeError, ProfileValidationError) as exc:
        logger.error("users.json invalid: %s", exc)
        return 2
    if not specs:
        logger.error("users.json has zero users")
        return 2

    providers = args.providers if args.providers else None
    data_dir = Path(args.data_dir)
    search_top_k = (
        args.search_top_k
        if args.search_top_k is not None
        else recommender._SEARCH_TOP_K_INTERESTS
    )
    use_search = bool(args.use_search) and search_top_k > 0

    last30days_config: dict[str, Any] | None = None
    if args.source in ("last30days", "both"):
        cli_path_str = args.last30days_cli_path
        if cli_path_str is None:
            logger.error(
                "--source %s requires --last30days-cli-path or "
                "[last30days] cli_path in config",
                args.source,
            )
            return 2
        last30days_config = {
            "cli_path": cli_path_str,
            "query": args.last30days_query,
            "days": args.last30days_days,
            "fetch_bodies": bool(args.last30days_fetch_bodies),
            "timeout": args.last30days_timeout,
            "save_dir": args.last30days_save_dir or str(data_dir / "last30days"),
            "platforms": (),
        }

    try:
        results = run_all_users_sync(
            users_path=users_path,
            data_dir=data_dir,
            max_parallel=args.max_parallel,
            limit=args.limit,
            body_preview_chars=args.body_preview_chars,
            per_user_timeout=args.per_user_timeout,
            providers=providers,
            config_path=Path(args.config),
            use_search=use_search,
            prefer_search=bool(args.prefer_search),
            search_providers=args.search_providers,
            search_top_k=search_top_k,
            search_results_per_interest=args.search_results_per_interest,
            source=args.source,
            last30days_config=last30days_config,
        )
    except Exception:
        logger.exception("fatal error in run_all_users")
        return 4

    envelope = output.build_envelope(
        users=results,
        llm_model="MiniMax-M2.7",
        embedding_model="bge-m3",
        config_version="0.3.186+mur.1",
    )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(output_path)
    except OSError as exc:
        logger.error("failed to write %s: %s", output_path, exc)
        return 4

    return _exit_code_for(results)


if __name__ == "__main__":
    sys.exit(main())
