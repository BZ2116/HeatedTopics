import argparse
from datetime import datetime, timezone
from pathlib import Path

from heated_topics_v3.pipeline import run_juejin_pipeline, run_toutiao_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HeatedTopics V3 workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    juejin = subparsers.add_parser("juejin", help="Collect Juejin hot list and match it to a user profile.")
    _add_platform_args(juejin)

    toutiao = subparsers.add_parser("toutiao", help="Collect Toutiao hot list and match it to a user profile.")
    _add_platform_args(toutiao)

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
        outputs = run_toutiao_pipeline(
            profile_path=args.profile,
            output_root=args.output_root,
            fetched_at=fetched_at,
        )
        for name, path in outputs.items():
            print(f"{name}: {path}")


def _add_platform_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--fetched-at", default=None)


if __name__ == "__main__":
    main()
