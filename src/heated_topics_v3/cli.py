import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from heated_topics_v3.baidu_retry import BaiduRetryPolicy
from heated_topics_v3.fetcher_factory import make_baidu_fetcher, make_search_fetcher
from heated_topics_v3.hot_board_cache import utc8_today
from heated_topics_v3.llm_client import call_llm, load_llm_config
from heated_topics_v3.llm_keywords import KEYWORD_EXTRACTION_SYSTEM, extract_persona_keywords
from heated_topics_v3.pipeline import (
    run_baidu_pipeline,
    run_juejin_pipeline,
    run_juejin_pipeline_v2,
    run_toutiao_pipeline,
    run_toutiao_pipeline_v2,
)
from heated_topics_v3.persona_intake import register_persona
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
    _add_juejin_args(juejin)

    toutiao = subparsers.add_parser("toutiao", help="Collect Toutiao hot list and match it to a user profile.")
    _add_toutiao_args(toutiao)

    baidu = subparsers.add_parser("baidu", help="Collect Baidu hot search and match it to a user profile.")
    _add_baidu_args(baidu)

    bilibili = subparsers.add_parser("bilibili", help="Collect Bilibili 专栏 by keyword and match to a profile.")
    _add_bilibili_args(bilibili)

    sina_news = subparsers.add_parser("sina-news", help="Collect Sina News hot list + per-keyword search and match to a profile.")
    _add_news_args(sina_news)

    netease_news = subparsers.add_parser("netease-news", help="Collect NetEase News hot list + per-keyword search and match to a profile.")
    _add_news_args(netease_news)

    refresh_kw = subparsers.add_parser("refresh-keywords", help="Delete keyword cache for one or all users, forcing LLM re-extraction on next run.")
    _add_refresh_keywords_args(refresh_kw)

    register = subparsers.add_parser("register", help="Register a new user persona: raw text -> structured profile + LLM keywords.")
    _add_register_args(register)

    subparsers.add_parser("check-llm", help="Test the configured LLM without reading or writing response cache.")

    args = parser.parse_args()
    if args.command == "juejin":
        fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if getattr(args, "profile_v2", None) is not None:
            from heated_topics_v3.fetcher_factory import make_juejin_fetcher
            fetcher = make_juejin_fetcher(log_path=Path(__file__).resolve().parent.parent / ".juejin_fetcher_log.json")
            result = run_juejin_pipeline_v2(
                profile_path=args.profile_v2, output_root=args.output_root, fetched_at=fetched_at,
                cache_root=args.cache_root, top_n=args.top_n, offline=args.offline,
                force_rank_refresh=args.force_rank_refresh, force_search_refresh=args.force_search_refresh,
                force_article_refresh=args.force_article_refresh,
                matched_query_ids=tuple(q.strip() for q in args.matched_query_ids if q.strip()),
                fetcher=fetcher, detail_fetcher=fetcher)
            for name, path in result.items():
                print(f"{name}: {path}")
        else:
            outputs = run_juejin_pipeline(
                profile_path=args.profile, output_root=args.output_root, fetched_at=fetched_at)
            for name, path in outputs.items():
                print(f"{name}: {path}")
    if args.command == "toutiao":
        fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if args.profile_v2 is not None:
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
                paced=False,
            )
            result = run_toutiao_pipeline_v2(
                profile_path=args.profile_v2,
                output_root=args.output_root,
                fetched_at=fetched_at,
                hot_board_cache_root=args.cache_root,
                persona_keyword_cache_root=args.cache_root / "core_keywords",
                force_hot_board_refresh=args.force_hot_board_refresh,
                offline=args.offline,
                top_n=args.top_n,
                custom_keywords=custom_keywords,
                on_search_committed=on_search_committed,
                fetcher=fetcher,
            )
            print(f"run_dir: {result.run_dir}")
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
    if args.command == "baidu":
        _handle_baidu(args)
    if args.command == "bilibili":
        _handle_bilibili(args)
    if args.command == "sina-news":
        _handle_sina_news(args)
    if args.command == "netease-news":
        _handle_netease_news(args)
    if args.command == "refresh-keywords":
        _handle_refresh_keywords(args)
    if args.command == "register":
        _handle_register(args)
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


def _add_register_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--level1", required=True, help="一级赛道，如 科技AI")
    parser.add_argument("--level2", required=True, help="二级赛道，如 AI工具应用")
    parser.add_argument("--persona-text", dest="persona_text", required=True, help="自然语言描述的人设，如 财经专业学生，关注基金和理财，喜欢分享实用技巧")
    parser.add_argument("--profiles-dir", dest="profiles_dir", default=Path("config/profiles"), type=Path)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--no-llm", dest="no_llm", action="store_true", help="跳过 LLM 结构化和关键词生成，使用启发式规则")


def _handle_register(args) -> None:
    cache_dir = args.cache_root / "core_keywords"
    result = register_persona(
        level1=args.level1,
        level2=args.level2,
        persona_text=args.persona_text,
        profiles_dir=args.profiles_dir,
        keyword_cache_dir=cache_dir,
        use_llm=not args.no_llm,
        structurer_llm=lambda p, s, **kw: call_llm(p, system=s, **kw),
        keyword_llm=lambda p, s, **kw: call_llm(p, system=s, **kw),
    )
    print(f"user_id: {result.user_id}")
    print(f"profile: {result.profile_path}")
    keywords = [k.keyword for k in result.keywords]
    print(f"keywords ({len(keywords)}): {keywords}")


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


def _add_baidu_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--top-n", dest="top_n", default=30, type=int)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force-board-refresh", dest="force_board_refresh", action="store_true")
    parser.add_argument("--force-search-refresh", dest="force_search_refresh", action="store_true")
    parser.add_argument("--force-article-refresh", dest="force_article_refresh", action="store_true")
    parser.add_argument("--baidu-cookie-path", dest="baidu_cookie_path", default=Path(".baidu_cookie"), type=Path)
    parser.add_argument("--matched-query-ids", dest="matched_query_ids", action="append", default=[])


def _add_bilibili_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--top-n", dest="top_n", default=20, type=int)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force-search-refresh", dest="force_search_refresh", action="store_true")
    parser.add_argument("--force-article-refresh", dest="force_article_refresh", action="store_true")
    parser.add_argument("--bilibili-cookie-path", dest="bilibili_cookie_path", default=Path(".bilibili_cookie"), type=Path)
    parser.add_argument("--matched-query-ids", dest="matched_query_ids", action="append", default=[])


def _add_news_args(parser: argparse.ArgumentParser) -> None:
    """Shared arg set for sina-news / netease-news (identical surface)."""
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--top-n", dest="top_n", default=10, type=int, help="Number of candidates to keep (default: 10)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force-board-refresh", dest="force_board_refresh", action="store_true")
    parser.add_argument("--force-search-refresh", dest="force_search_refresh", action="store_true")
    parser.add_argument("--force-article-refresh", dest="force_article_refresh", action="store_true")
    parser.add_argument("--matched-query-ids", dest="matched_query_ids", action="append", default=[])
    parser.add_argument("--custom-keyword", dest="custom_keyword", action="append", default=[])
    parser.add_argument("--state-root", default=Path("state"), type=Path)
    parser.add_argument("--max-quota-per-day", dest="max_quota_per_day", default=3, type=int)
    parser.add_argument("--skip-quota", dest="skip_quota", action="store_true")


def _add_juejin_args(parser: argparse.ArgumentParser) -> None:
    profiles = parser.add_mutually_exclusive_group(required=True)
    profiles.add_argument("--profile", type=Path)
    profiles.add_argument("--profile-v2", dest="profile_v2", type=Path)
    parser.add_argument("--output-root", "--output-dir", dest="output_root", default=Path("outputs"), type=Path)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--cache-root", default=Path("cache"), type=Path)
    parser.add_argument("--top-n", dest="top_n", default=20, type=int)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force-rank-refresh", dest="force_rank_refresh", action="store_true")
    parser.add_argument("--force-search-refresh", dest="force_search_refresh", action="store_true")
    parser.add_argument("--force-article-refresh", dest="force_article_refresh", action="store_true")
    parser.add_argument("--matched-query-ids", dest="matched_query_ids", action="append", default=[])


def _handle_bilibili(args) -> None:
    from heated_topics_v3.fetcher_factory import make_bilibili_fetcher
    from heated_topics_v3.pipeline import run_bilibili_pipeline

    fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    matched_query_ids = tuple(q.strip() for q in args.matched_query_ids if q.strip())
    log_path = Path(__file__).resolve().parent.parent / ".bilibili_fetcher_log.json"
    cookie = args.bilibili_cookie_path if Path(args.bilibili_cookie_path).exists() else None
    fetcher = make_bilibili_fetcher(log_path=log_path, cookie_path=cookie)
    outputs = run_bilibili_pipeline(
        profile_path=args.profile,
        output_root=args.output_root,
        fetched_at=fetched_at,
        cache_root=args.cache_root,
        top_n=args.top_n,
        offline=args.offline,
        force_search_refresh=args.force_search_refresh,
        force_article_refresh=args.force_article_refresh,
        matched_query_ids=matched_query_ids,
        fetcher=fetcher,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")


def _handle_baidu(args) -> None:
    fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    matched_query_ids = tuple(q.strip() for q in args.matched_query_ids if q.strip())
    log_path = Path(__file__).resolve().parent.parent / ".baidu_fetcher_log.json"
    fetcher = make_baidu_fetcher(log_path=log_path, retry_policy=BaiduRetryPolicy())
    outputs = run_baidu_pipeline(
        profile_path=args.profile,
        output_root=args.output_root,
        fetched_at=fetched_at,
        cache_root=args.cache_root,
        top_n=args.top_n,
        offline=args.offline,
        force_board_refresh=args.force_board_refresh,
        force_search_refresh=args.force_search_refresh,
        force_article_refresh=args.force_article_refresh,
        matched_query_ids=matched_query_ids,
        cookie_path=args.baidu_cookie_path,
        fetcher=fetcher,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")


def _handle_sina_news(args) -> None:
    """Mirror of ``_handle_bilibili`` for the Sina News pipeline."""
    from heated_topics_v3.fetcher_factory import make_sina_news_fetcher
    from heated_topics_v3.pipeline import run_sina_news_pipeline

    fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    matched_query_ids = tuple(q.strip() for q in args.matched_query_ids if q.strip())
    custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())
    today = utc8_today()

    on_search_committed = None
    if not args.skip_quota:
        from heated_topics_v3.pipeline import load_user_profile
        profile = load_user_profile(args.profile)
        user_id = getattr(profile, "profile_id", None) or ""
        if not user_id:
            print("profile 缺少 profile_id，无法应用配额；请用 --skip-quota", file=sys.stderr)
            raise SystemExit(2)
        state = load_quota(args.state_root, user_id, today)
        try:
            check_quota(state, args.max_quota_per_day)
        except QuotaExceededError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        def _commit() -> None:
            commit_quota(args.state_root, user_id, today)
        on_search_committed = _commit

    log_path = Path(__file__).resolve().parent.parent / ".sina_news_fetcher_log.json"
    fetcher = make_sina_news_fetcher(log_path=log_path, retry_policy=BaiduRetryPolicy())
    result = run_sina_news_pipeline(
        profile_path=args.profile,
        output_root=args.output_root,
        fetched_at=fetched_at,
        cache_root=args.cache_root,
        top_n=args.top_n,
        offline=args.offline,
        force_board_refresh=args.force_board_refresh,
        force_search_refresh=args.force_search_refresh,
        force_article_refresh=args.force_article_refresh,
        matched_query_ids=matched_query_ids,
        custom_keywords=custom_keywords,
        on_search_committed=on_search_committed,
        fetcher=fetcher,
    )
    print(f"run_dir: {result.run_dir}")
    print(f"focused: {result.focused_path}")
    print(f"candidates: {result.kept_total}/{result.candidates_total}")
    print(f"paths: {result.paths}")
    print(f"hot_board_source: {result.hot_board_source}")
    print(f"keyword_source: {result.keyword_source}")
    print(f"keyword_count: {result.keyword_count}")


def _handle_netease_news(args) -> None:
    """Mirror of ``_handle_sina_news`` for the NetEase News pipeline."""
    from heated_topics_v3.fetcher_factory import make_netease_news_fetcher
    from heated_topics_v3.pipeline import run_netease_news_pipeline

    fetched_at = args.fetched_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    matched_query_ids = tuple(q.strip() for q in args.matched_query_ids if q.strip())
    custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())
    today = utc8_today()

    on_search_committed = None
    if not args.skip_quota:
        from heated_topics_v3.pipeline import load_user_profile
        profile = load_user_profile(args.profile)
        user_id = getattr(profile, "profile_id", None) or ""
        if not user_id:
            print("profile 缺少 profile_id，无法应用配额；请用 --skip-quota", file=sys.stderr)
            raise SystemExit(2)
        state = load_quota(args.state_root, user_id, today)
        try:
            check_quota(state, args.max_quota_per_day)
        except QuotaExceededError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        def _commit() -> None:
            commit_quota(args.state_root, user_id, today)
        on_search_committed = _commit

    log_path = Path(__file__).resolve().parent.parent / ".netease_news_fetcher_log.json"
    fetcher = make_netease_news_fetcher(log_path=log_path, retry_policy=BaiduRetryPolicy())
    result = run_netease_news_pipeline(
        profile_path=args.profile,
        output_root=args.output_root,
        fetched_at=fetched_at,
        cache_root=args.cache_root,
        top_n=args.top_n,
        offline=args.offline,
        force_board_refresh=args.force_board_refresh,
        force_search_refresh=args.force_search_refresh,
        force_article_refresh=args.force_article_refresh,
        matched_query_ids=matched_query_ids,
        custom_keywords=custom_keywords,
        on_search_committed=on_search_committed,
        fetcher=fetcher,
    )
    print(f"run_dir: {result.run_dir}")
    print(f"focused: {result.focused_path}")
    print(f"candidates: {result.kept_total}/{result.candidates_total}")
    print(f"paths: {result.paths}")
    print(f"hot_board_source: {result.hot_board_source}")
    print(f"keyword_source: {result.keyword_source}")
    print(f"keyword_count: {result.keyword_count}")


if __name__ == "__main__":
    main()
