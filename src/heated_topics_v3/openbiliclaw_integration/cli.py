"""CLI entry point for the openbiliclaw_integration recommender (v2).

Reads users from .xlsx, writes per-user/per-date files under --output-dir.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from heated_topics_v3.clock import SHANGHAI
from heated_topics_v3.openbiliclaw_integration import (
    excel_loader,
    output,
    recommender,
    runtime,
)
from heated_topics_v3.openbiliclaw_integration.exceptions import ProfileValidationError

logger = logging.getLogger(__name__)


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
            "Per-user output root. CLI writes "
            "{output-dir}/{user_id}/{YYYY-MM-DD}/recommendations.json"
        ),
    )
    p.add_argument("--limit", type=int, default=8, help="Top-N per user (default 8)")
    p.add_argument(
        "--max-parallel", type=int, default=5,
        help="Max concurrent users (default 5; 1 = serial)",
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
    return p.parse_args(list(argv))


def run_all_users_sync(**kwargs: Any) -> dict[str, dict[str, Any]]:
    """Sync wrapper for tests. Real implementation calls asyncio.run."""
    return asyncio_run(recommender.run_all_users(**kwargs))


def asyncio_run(coro: Any) -> Any:
    """Trivial indirection so tests can patch asyncio.run if needed."""
    import asyncio
    return asyncio.run(coro)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. Writes one {user_id}/{date}/recommendations.json per user."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = parse_args(argv if argv is not None else sys.argv[1:])

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
        }

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
        )
    except Exception:
        logger.exception("fatal error in run_all_users")
        return 4

    today = datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    any_error = False
    for user_id, payload in results.items():
        user_dir = args.output_dir / user_id / today
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
            target = user_dir / "recommendations.json"
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(target)
        except OSError as exc:
            logger.error("failed to write %s: %s", user_dir, exc)
            any_error = True
        if "error" in payload:
            any_error = True

    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())