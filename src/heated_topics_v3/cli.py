import argparse
from datetime import datetime, timezone
from pathlib import Path

from heated_topics_v3.pipeline import run_juejin_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HeatedTopics V3 workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    juejin = subparsers.add_parser("juejin", help="Collect Juejin hot list and match it to a user profile.")
    juejin.add_argument("--profile", required=True, type=Path)
    juejin.add_argument("--output-dir", default=Path("outputs/juejin"), type=Path)
    juejin.add_argument("--fetched-at", default=None)

    args = parser.parse_args()
    if args.command == "juejin":
        fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        outputs = run_juejin_pipeline(
            profile_path=args.profile,
            output_dir=args.output_dir,
            fetched_at=fetched_at,
        )
        for name, path in outputs.items():
            print(f"{name}: {path}")


if __name__ == "__main__":
    main()
