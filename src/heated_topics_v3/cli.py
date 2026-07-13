"""Command-line entry points for the anonymous Toutiao and Juejin V1 workflow."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Sequence

import httpx

from .clock import SHANGHAI
from .collection import collect_v1_daily
from .profiles import load_profile
from .providers.juejin import JuejinProvider
from .providers.toutiao import ToutiaoProvider
from .recommendation import generate_v1_user_result
from .storage import FileRepository


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="heated-topics", add_help=True)
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect-v1")
    collect.add_argument("--data-root", type=Path, required=True)

    generate = commands.add_parser("generate-v1")
    generate.add_argument("--data-root", type=Path, required=True)
    generate.add_argument("--profile", type=Path, required=True)
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": "heatedtopics-v1/0.1 (+anonymous-public-data)"},
    )


def _collect(data_root: Path) -> tuple[int, dict[str, object]]:
    started = time.monotonic()
    now = datetime.now(SHANGHAI)
    repository = FileRepository(data_root)
    with _client() as client:
        snapshot = collect_v1_daily(
            now,
            repository,
            {
                "toutiao": ToutiaoProvider(client),
                "juejin": JuejinProvider(client),
            },
        )
    platforms = {
        status.platform: {
            "status": status.status,
            "item_count": status.item_count,
        }
        for status in snapshot.platform_statuses
    }
    statuses = tuple(status.status for status in snapshot.platform_statuses)
    if statuses and all(status == "failed" for status in statuses):
        overall = "failed"
        exit_code = 1
    elif any(status != "success" for status in statuses):
        overall = "partial"
        exit_code = 0
    else:
        overall = "success"
        exit_code = 0
    return exit_code, {
        "status": overall,
        "command": "collect-v1",
        "business_date": snapshot.business_date,
        "data_root": str(data_root.resolve()),
        "platforms": platforms,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _generate(data_root: Path, profile_path: Path) -> tuple[int, dict[str, object]]:
    started = time.monotonic()
    now = datetime.now(SHANGHAI)
    repository = FileRepository(data_root)
    profile = load_profile(profile_path)
    with _client() as client:
        bundle = generate_v1_user_result(
            profile,
            now,
            repository,
            ToutiaoProvider(client),
        )
    successful = bundle.status in {"generated", "no_result", "existing"}
    return (0 if successful else 1), {
        "status": bundle.status,
        "command": "generate-v1",
        "user_id": bundle.user_id,
        "business_date": bundle.business_date,
        "recommendation_count": len(bundle.recommendations),
        "potential_topic_count": len(bundle.potential_topics),
        "result_dir": str(
            (
                data_root
                / "user_results"
                / bundle.user_id
                / bundle.business_date
            ).resolve()
        ),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one V1 command and emit exactly one machine-readable JSON status."""
    try:
        arguments = _parser().parse_args(argv)
    except _ArgumentError:
        _emit({"status": "failed", "error": "invalid_arguments"})
        return 2
    except SystemExit as exit_status:
        return int(exit_status.code)

    try:
        if arguments.command == "collect-v1":
            exit_code, payload = _collect(arguments.data_root)
        else:
            exit_code, payload = _generate(arguments.data_root, arguments.profile)
    except Exception as error:
        _emit(
            {
                "status": "failed",
                "command": arguments.command,
                "error": type(error).__name__,
            }
        )
        return 1
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
