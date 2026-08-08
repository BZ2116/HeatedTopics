"""CLI entry point for the openbiliclaw_integration recommender (v2).

Reads users from .xlsx, writes per-user/per-date files under --output-dir.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from heated_topics_v3.openbiliclaw_integration import (
    excel_loader,
    recommender,
    report_writer,
    runtime,
)
from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError

logger = logging.getLogger(__name__)


def _next_round_name(user_dir: Path) -> str:
    """Return the next round name without touching existing run artifacts."""
    numbers = []
    if user_dir.exists():
        for child in user_dir.iterdir():
            if child.is_dir() and child.name.startswith("round_"):
                try:
                    numbers.append(int(child.name.removeprefix("round_")))
                except ValueError:
                    pass
    return f"round_{max(numbers, default=0) + 1:03d}"


def _default_last30days_cli_path() -> Path | None:
    """Find the sibling last30days checkout without OS-specific paths."""
    configured = os.getenv("LAST30DAYS_CLI_PATH", "").strip()
    candidates = [Path(configured)] if configured else []
    project_root = Path(__file__).resolve().parents[3]
    candidates.append(project_root / "last30days-skill-cn" / "scripts" / "last30days.py")
    candidates.extend(
        parent / "last30days-skill-cn" / "scripts" / "last30days.py"
        for parent in project_root.parents
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _limit_1_15(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 15:
        raise argparse.ArgumentTypeError("limit must be between 1 and 15")
    return parsed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI args. V2 surface — keep this small."""
    p = argparse.ArgumentParser(
        prog="python -m heated_topics_v3.openbiliclaw_integration.cli",
        description=(
            "Per-user creator material recommender "
            "(v2: Excel in, per-user/date files out)."
        ),
    )
    p.add_argument(
        "--users-excel", required=True, type=Path,
        help="Path to users.xlsx (4 cols: user_id, track_1, track_2, persona)",
    )
    p.add_argument(
        "--output-dir", required=True, type=Path,
        help=(
            "Per-run output root. CLI writes "
            "{output-dir}/inputs/users.json and "
            "{output-dir}/outputs/{user_id}/{input.json,queries/,summaries/,text/}"
        ),
    )
    p.add_argument("--limit", type=_limit_1_15, default=15, help="Top-N per user (default 15, maximum 15)")
    p.add_argument(
        "--max-parallel", type=int, choices=range(1, 4), default=3,
        help="Max concurrent users (1-3, default 3)",
    )
    p.add_argument(
        "--per-user-timeout", type=float, default=300.0,
        help="Per-user timeout in seconds (default 300)",
    )
    p.add_argument(
        "--body-max-chars", type=int, default=50_000,
        help="Cap on stored body_text length (default 50000)",
    )
    p.add_argument(
        "--source", choices=("v3-hotlist", "last30days", "both"), default="both",
        help="Candidate source (default both: V3 + last30days)",
    )
    p.add_argument(
        "--last30days-cli-path", type=Path, default=None,
        help=(
            "Path to last30days's scripts/last30days.py "
            "(required if source includes last30days)"
        ),
    )
    p.add_argument(
        "--last30days-days", type=int, default=30,
        help="Days back for last30days (default 30)",
    )
    p.add_argument(
        "--last30days-fetch-bodies", dest="last30days_fetch_bodies",
        action="store_true", default=True,
        help="Enable --fetch-bodies on last30days (default on)",
    )
    p.add_argument(
        "--no-last30days-fetch-bodies", dest="last30days_fetch_bodies",
        action="store_false",
        help="Disable --fetch-bodies on last30days",
    )
    p.add_argument(
        "--last30days-timeout", type=float, default=120.0,
        help="Per-user last30days subprocess timeout (default 120)",
    )
    p.add_argument(
        "--last30days-max-queries", type=int, default=3,
        help=(
            "Max number of last30days queries per user (default 3). "
            "Each LLM-extracted keyword becomes one CLI query; this caps "
            "the total. Set to 1 to restore single-query behaviour. "
            "Ignored when --last30days-query is supplied multiple times."
        ),
    )
    p.add_argument(
        "--last30days-low-water-mark", type=int, default=3,
        help=(
            "Adaptive escalation threshold (default 3). After each "
            "query, if article count exceeds this the pipeline stops "
            "early; otherwise the next query is tried. Set high to "
            "always run --last30days-max-queries queries."
        ),
    )
    p.add_argument(
        "--last30days-query", dest="last30days_queries", action="append",
        default=None,
        help=(
            "Explicit last30days query (repeatable). Overrides the "
            "LLM-extracted keyword list when supplied. Example: "
            "--last30days-query 古典文学 --last30days-query 诗词"
        ),
    )
    p.add_argument(
        "--no-keyword-extraction", dest="keyword_extraction",
        action="store_false", default=True,
        help=(
            "Skip LLM-driven keyword extraction; fall back to "
            "track_1/track_2 as search queries. Default: extract 3 "
            "keywords from track_1/track_2/persona via LLM, cache "
            "per user under _keyword_cache/."
        ),
    )
    p.add_argument(
        "--min-view-count", type=int, default=0,
        help=(
            "Drop candidates whose heat.view is below this threshold "
            "(default 0 = no filter). Useful for filtering low-engagement "
            "long-tail picks from v3-hotlist or last30days."
        ),
    )
    p.add_argument(
        "--heat-source", choices=("rank", "view"), default="rank",
        help=(
            "Heat factor for relevance scoring: 'rank' uses 1/rank "
            "(v2.1.2 default); 'view' uses log(view+1)/log(100001) and "
            "falls back to rank when view_count is missing/zero."
        ),
    )
    p.add_argument(
        "--llm-refilter", dest="llm_refilter",
        action="store_true", default=False,
        help=(
            "After the embedding pre-filter, ask the LLM to drop "
            "candidates that look keyword-relevant but are off-persona. "
            "Adds one LLM call per ~10 candidates. Off by default."
        ),
    )
    p.add_argument(
        "--refilter-batch-size", type=int, default=10,
        help=(
            "Candidates per LLM refilter batch "
            "(default 10; smaller = more calls but tighter judgments)."
        ),
    )
    return p.parse_args(list(argv))


def run_all_users_sync(**kwargs: Any) -> dict[str, dict[str, Any]]:
    """Sync wrapper for tests. Real implementation calls asyncio.run."""
    return asyncio_run(recommender.run_all_users(**kwargs))


def asyncio_run(coro: Any) -> Any:
    """Trivial indirection so tests can patch asyncio.run if needed."""
    import asyncio
    return asyncio.run(coro)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. Writes inputs/users.json + outputs/{user_id}/{layout} per user."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.last30days_cli_path is None:
        args.last30days_cli_path = _default_last30days_cli_path()

    # Fail-fast
    runtime.verify_patch()
    missing = runtime.check_env()
    if missing:
        logger.error("Missing env vars: %s", ", ".join(missing))
        return 2
    if args.source in ("last30days", "both") and args.last30days_cli_path is None:
        logger.error(
            "--source %s requires --last30days-cli-path", args.source,
        )
        return 2

    try:
        specs = excel_loader.load_excel(args.users_excel)
    except (FileNotFoundError, ProfileValidationError, ValueError) as exc:
        logger.error("Excel invalid: %s", exc)
        return 2
    if not specs:
        logger.error("Excel has zero users")
        return 2

    last30days_config: dict[str, Any] | None = None
    if args.source in ("last30days", "both"):
        last30days_config = {
            "cli_path": str(args.last30days_cli_path),
            "days": args.last30days_days,
            "fetch_bodies": args.last30days_fetch_bodies,
            "timeout": args.last30days_timeout,
            "save_dir": str(args.output_dir / "last30days"),
            "platforms": (),
            "low_water_mark": args.last30days_low_water_mark,
        }
        if args.last30days_queries:
            last30days_config["queries"] = list(args.last30days_queries)

    try:
        results = run_all_users_sync(
            specs=specs,
            data_dir=args.output_dir / "_runtime",
            max_parallel=args.max_parallel,
            limit=args.limit,
            body_max_chars=args.body_max_chars,
            per_user_timeout=args.per_user_timeout,
            source=args.source,
            last30days_config=last30days_config,
            last30days_max_queries=args.last30days_max_queries,
            use_keyword_extraction=args.keyword_extraction,
            keyword_cache_dir=None,
            user_cache_root=args.output_dir,
            hot_cache_dir=args.output_dir / "hot_cache",
            min_view_count=args.min_view_count,
            heat_source=args.heat_source,
            use_llm_refilter=args.llm_refilter,
            refilter_batch_size=args.refilter_batch_size,
        )
    except Exception:
        logger.exception("fatal error in run_all_users")
        return 4

    # Persist the inputs registry once for the whole run so a re-run with
    # identical Excel produces a byte-identical inputs/users.json.
    report_writer.write_inputs_registry(args.output_dir, specs)

    any_error = False
    for user_id, payload in results.items():
        try:
            user_dir = args.output_dir / user_id
            round_root = user_dir / _next_round_name(user_dir)
            inp = payload.get("input", {}) or {}
            report_writer.write_user_report(
                round_root / "outputs",
                user_id=user_id,
                track_1=inp.get("track_1", ""),
                track_2=inp.get("track_2", ""),
                persona=inp.get("persona", ""),
                recommendations=payload.get("recommendations") or [],
                searched_articles=payload.get("searched_articles") or [],
                summary=payload.get("summary") or "",
                body_max_chars=args.body_max_chars,
            )
            input_dir = round_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "input.json").write_text(
                json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.error("failed to write %s: %s", user_dir, exc)
            any_error = True
        if "error" in payload:
            any_error = True

    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
