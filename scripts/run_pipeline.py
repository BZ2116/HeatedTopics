"""Single-user smoke run for run_toutiao_pipeline_v2.

Drives the pipeline for `yingjie_001` against the canonical profile at
`config/profiles/yingjie_001.json`, with cookie + fetcher_log + cache
all living under `scripts/` so smoke runs stay isolated from real
output. Run `harvest_cookies.py` first if `.toutiao_cookie` is missing
or stale.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from heated_topics_v3.fetcher_factory import make_search_fetcher
from heated_topics_v3.pipeline import run_toutiao_pipeline_v2


def main() -> None:
    profile_path = REPO_ROOT / "config" / "profiles" / "yingjie_001.json"
    output_root = ROOT / "output"
    cache_root = ROOT / "cache"
    fetched_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")

    fetcher = make_search_fetcher(
        cookie_path=ROOT / ".toutiao_cookie",
        log_path=ROOT / ".fetcher_log.json",
        timeout=30,
    )

    result = run_toutiao_pipeline_v2(
        profile_path=profile_path,
        output_root=output_root,
        fetched_at=fetched_at,
        hot_board_cache_root=cache_root,
        persona_keyword_cache_root=cache_root / "core_keywords",
        llm_cache_root=cache_root / "llm",
        use_llm_keywords=True,
        use_llm_summary=False,
        use_llm_rerank=False,
        top_n=10,
        fetcher=fetcher,
    )
    print(f"run_dir: {result.run_dir}")
    print(f"user_id: {result.user_id}")
    print(f"date: {result.date}")
    print(f"candidates_total: {result.candidates_total}")
    print(f"kept_total: {result.kept_total}")
    print(f"keyword_count: {result.keyword_count}")
    print(f"hot_board_source: {result.hot_board_source}")
    print(f"keyword_source: {result.keyword_source}")
    print(f"paths: {result.paths}")
    print(f"report: {result.report_path}")
    print(f"focused: {result.focused_path}")
    print(f"fetcher.stage at end: {fetcher.stage()}")
    print(f"fetcher.disabled: {fetcher.disabled()}")


if __name__ == "__main__":
    main()
