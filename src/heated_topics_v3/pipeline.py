import json
import math
import time
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from heated_topics_v3.contracts import ExtractedKeyword, HeatMetrics, HotItem, ItemDetail, MatchResult, UserProfile
from heated_topics_v3.baidu_cache import (
    get_or_fetch_article_with_record,
    get_or_fetch_board_with_record,
    get_or_fetch_search_with_record,
)
from heated_topics_v3.hot_board_cache import get_or_fetch_hot_board, hot_board_cache_path, utc8_today
from heated_topics_v3.llm_keywords import PersonaKeywordExtraction
from heated_topics_v3.matching import match_hot_item_to_queries
from heated_topics_v3.profile_loader import is_legacy_profile, load_persona_profile
from heated_topics_v3.profile_queries import build_topic_queries
from heated_topics_v3.providers.baidu import (
    BaiduSearchArticle,
    fetch_baidu_article_text,
    fetch_baidu_board_text,
    fetch_baidu_search_text,
    parse_baidu_article_response,
    parse_baidu_board_response,
    parse_baidu_search_response,
)
from heated_topics_v3.providers.juejin import fetch_juejin_hot_items, fetch_juejin_item_detail
from heated_topics_v3.juejin_cache import (
    get_or_fetch_board_with_record as juejin_get_rank,
    get_or_fetch_search_with_record as juejin_get_search,
    get_or_fetch_article_with_record as juejin_get_article,
)
from heated_topics_v3.providers.juejin import (
    fetch_juejin_search_items,
    merge_juejin_items,
    parse_juejin_rank_response,
    parse_juejin_search_response,
)
from heated_topics_v3.reporting import render_juejin_report_v2
from heated_topics_v3.providers.toutiao import (
    attach_article_heat_fields,
    build_toutiao_search_phrases,
    extract_toutiao_article_id,
    fetch_toutiao_article_info,
    fetch_toutiao_hot_items,
    fetch_toutiao_item_details,
    fetch_toutiao_search_items,
    fetch_toutiao_search_pages,
    merge_toutiao_items,
    resolve_toutiao_content_url,
)
from heated_topics_v3.reporting import (
    BaiduCacheStats,
    render_baidu_report,
    render_bilibili_report,
    render_juejin_report,
    render_toutiao_report,
    render_toutiao_report_v2,
)
from heated_topics_v3.bilibili_cache import (
    get_or_fetch_article_with_record as bilibili_get_article,
    get_or_fetch_search_with_record as bilibili_get_search,
)
from heated_topics_v3.providers.bilibili import (
    fetch_bilibili_article_text,
    fetch_bilibili_nav,
    fetch_bilibili_search_text,
    build_search_url,
    parse_bilibili_article_response,
    parse_bilibili_search_response,
)
from heated_topics_v3.bilibili_wbi import img_sub_from_nav
from heated_topics_v3.serialization import to_plain_data
from heated_topics_v3.toutiao_output import write_toutiao_run
from heated_topics_v3.toutiao_paths import (
    PATH_B,
    Candidate,
    PathFilters,
    build_candidates,
    build_hot_board_candidates,
    select_search_candidates_by_heat,
)
from heated_topics_v3.toutiao_search_cache import get_or_fetch_search_items
from heated_topics_v3.toutiao_scoring import as_sort_key, hybrid_score_v2

def _fetch_text_default(url: str, timeout_seconds: int = 15) -> str:
    """Stand-in fetcher used when callers omit one — never silent, never online.

    The pipeline must surface a clear error rather than silently substituting a
    urllib fallback. Tests inject deterministic fetchers; CLI entrypoints in
    Task 7 wire a real fetcher. This helper only exists so the offline branch
    has something to bind to when no fetcher is provided.
    """
    raise RuntimeError(
        f"Baidu fetcher not provided and live mode unavailable for {url}"
    )


def run_baidu_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    search_fetcher: Callable[[str, int], str] | None = None,
    article_fetcher: Callable[[str, int], str] | None = None,
    cookie_path: Path | None = None,
    top_n: int = 30,
    offline: bool = False,
    force_board_refresh: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
) -> dict[str, Path]:
    """Three-stage Baidu pipeline: board → per-word search → per-article body."""
    profile = load_user_profile(profile_path)
    board_fetch = fetcher or _fetch_text_default
    search_fetch = search_fetcher or board_fetch
    article_fetch = article_fetcher or board_fetch
    # When cookie_path is supplied, the baijiahao anti-bot shell blocks
    # plain urllib — switch the article fetcher to one that combines the
    # cookie with a Chrome TLS fingerprint. Board/search remain on urllib.
    if cookie_path is not None and Path(cookie_path).exists():
        from heated_topics_v3.fetcher_factory import make_baidu_article_fetcher
        article_fetch = make_baidu_article_fetcher(cookie_path=cookie_path)

    today = utc8_today()
    cache_root_path = Path(cache_root)
    stats = BaiduCacheStats()

    # ---- stage 1: board ----
    def live_board(_date: str) -> dict[str, str]:
        return {"response_text": fetch_baidu_board_text(board_fetch)}

    if force_board_refresh:
        board_payload, src = get_or_fetch_board_with_record(
            cache_root_path,
            today,
            live_board,
            force_refresh=True,
        )
    elif offline:
        board_payload, src = get_or_fetch_board_with_record(
            cache_root_path, today, live_board, deadline=time.monotonic()
        )
    else:
        board_payload, src = get_or_fetch_board_with_record(
            cache_root_path, today, live_board
        )
    stats.record("board", src, forced=force_board_refresh)
    body = str(board_payload.get("response_text", "")) if isinstance(board_payload, dict) else ""
    # Offline mode with an empty cache yields an empty board marker (``{}``),
    # leaving ``body`` blank. ``parse_baidu_board_response`` assumes valid JSON,
    # so guard the empty case here and treat it as "no hot words" rather than
    # crashing on ``json.loads("")``.
    hot_words: list[HotItem] = (
        parse_baidu_board_response(
            body, fetched_at=fetched_at, matched_query_ids=matched_query_ids
        )
        if body.strip()
        else []
    )

    # ---- stage 2: per-word search → synthesized article HotItems ----
    expanded: list[HotItem] = []
    for word_item in hot_words[:top_n]:
        word = word_item.title

        def live_search(_w: str = word) -> list[dict[str, str]]:
            html = fetch_baidu_search_text(word, search_fetch)
            articles: list[BaiduSearchArticle] = parse_baidu_search_response(html, source_word=word)
            return [
                {
                    "article_id": a.article_id,
                    "title": a.title,
                    "url": a.url,
                    "source_word": a.source_word,
                }
                for a in articles
            ]

        if force_search_refresh:
            ids_payload, src = get_or_fetch_search_with_record(
                cache_root_path, today, word, live_search, force_refresh=True
            )
        elif offline:
            ids_payload, src = get_or_fetch_search_with_record(
                cache_root_path, today, word, live_search, deadline=time.monotonic()
            )
        else:
            ids_payload, src = get_or_fetch_search_with_record(
                cache_root_path, today, word, live_search
            )
        stats.record("search", src, forced=force_search_refresh)
        if not isinstance(ids_payload, list):
            continue
        # Keep at most ONE baijiahao article per hot word — the search page
        # surfaces many links, but only the first baijiahao entry represents
        # the word's most relevant recall. Capping here also keeps downstream
        # article-body fetches bounded and prevents one noisy page from
        # dominating the matched set.
        word_added = False
        for entry in ids_payload:
            if word_added:
                break
            if not isinstance(entry, dict):
                continue
            article_id = str(entry.get("article_id", "")).strip()
            if not article_id:
                continue
            word_added = True
            expanded.append(
                HotItem(
                    item_id=f"baidu_article_{article_id}",
                    platform="baidu",
                    item_type="article",
                    # Match against the actual article title from search
                    # results, not just the board hot word — the search page
                    # may surface an article whose subject diverges from the
                    # query term (e.g. board word "高考改革" → article titled
                    # "教育部新规：高考改革方案公布"). Fall back to the board
                    # word when no title was extracted.
                    title=str(entry.get("title") or word),
                    url=str(entry.get("url", "") or ""),
                    rank=None,
                    heat=HeatMetrics(value=None, label="", metric_name="search_recall", metrics={}),
                    summary="",
                    category="baijiahao",
                    matched_query_ids=matched_query_ids,
                    fetched_at=fetched_at,
                    fetch_status="success",
                    raw_payload={
                        "source_kind": "baidu_search_recall",
                        "source_path": "A",
                        "source_word": word,
                        "source_word_url": word_item.url,
                        "article_id": article_id,
                    },
                )
            )

    # ---- matching (pass 1: board-driven) ----
    queries = tuple(build_topic_queries(profile))
    matches = [
        result
        for item in expanded
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]

    # ---- fallback: keyword-driven search when board produced too few matches ----
    # Mirrors Toutiao's `min_hot_board_before_search` rule (pipeline.py:617):
    # if board-driven hits fall below the threshold, run profile.core_keywords
    # as additional search queries. Board items (path A) keep their priority
    # by being appended to ``expanded`` first; kw items (path B) append after.
    MIN_HOT_BOARD_BEFORE_SEARCH = 5
    if len(matches) < MIN_HOT_BOARD_BEFORE_SEARCH and profile.core_keywords:
        seen_article_ids = {
            str(item.raw_payload.get("article_id", "")).strip()
            for item in expanded
        }
        for keyword in profile.core_keywords:
            if not keyword.strip():
                continue

            def live_search(_w: str = keyword) -> list[dict[str, str]]:
                html = fetch_baidu_search_text(keyword, search_fetch)
                articles: list[BaiduSearchArticle] = parse_baidu_search_response(
                    html, source_word=keyword
                )
                return [
                    {
                        "article_id": a.article_id,
                        "title": a.title,
                        "url": a.url,
                        "source_word": a.source_word,
                    }
                    for a in articles
                ]

            if force_search_refresh:
                ids_payload, src = get_or_fetch_search_with_record(
                    cache_root_path, today, keyword, live_search, force_refresh=True
                )
            elif offline:
                ids_payload, src = get_or_fetch_search_with_record(
                    cache_root_path, today, keyword, live_search, deadline=time.monotonic()
                )
            else:
                ids_payload, src = get_or_fetch_search_with_record(
                    cache_root_path, today, keyword, live_search
                )
            stats.record("search", src, forced=force_search_refresh)
            if not isinstance(ids_payload, list):
                continue
            for entry in ids_payload:
                if not isinstance(entry, dict):
                    continue
                article_id = str(entry.get("article_id", "")).strip()
                if not article_id or article_id in seen_article_ids:
                    continue
                seen_article_ids.add(article_id)
                expanded.append(
                    HotItem(
                        item_id=f"baidu_article_{article_id}",
                        platform="baidu",
                        item_type="article",
                        title=str(entry.get("title") or keyword),
                        url=str(entry.get("url", "") or ""),
                        rank=None,
                        heat=HeatMetrics(
                            value=None, label="", metric_name="search_recall", metrics={}
                        ),
                        summary="",
                        category="baijiahao",
                        matched_query_ids=matched_query_ids,
                        fetched_at=fetched_at,
                        fetch_status="success",
                        raw_payload={
                            "source_kind": "keyword_search_recall",
                            "source_path": "B",
                            "source_word": keyword,
                            "article_id": article_id,
                        },
                    )
                )

        # Re-match with kw-driven items included (board items retain priority
        # because they precede kw items in ``expanded``).
        matches = [
            result
            for item in expanded
            if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
        ]

    # ---- stage 3: per-article body ----
    item_details: list[ItemDetail] = []
    for match in matches:
        item = match.item
        article_id = str(item.raw_payload.get("article_id", "")).strip()

        def live_article(_aid: str = article_id) -> dict[str, object]:
            html = fetch_baidu_article_text(article_id, article_fetch)
            detail = parse_baidu_article_response(
                html,
                item_id=item.item_id,
                item_url=item.url,
                fetched_at=fetched_at,
            )
            return {
                "title": item.title,
                "content": detail.content,
                "extraction_method": detail.extraction_method,
                "fetch_status": detail.fetch_status,
                "html_length": len(html),
            }

        if force_article_refresh:
            payload, src = get_or_fetch_article_with_record(
                cache_root_path, today, article_id, live_article, force_refresh=True
            )
        elif offline:
            payload, src = get_or_fetch_article_with_record(
                cache_root_path, today, article_id, live_article, deadline=time.monotonic()
            )
        else:
            payload, src = get_or_fetch_article_with_record(
                cache_root_path, today, article_id, live_article
            )
        stats.record("article", src, forced=force_article_refresh)
        if not isinstance(payload, dict) or not payload:
            detail = ItemDetail(
                item_id=item.item_id,
                platform=item.platform,
                url=item.url,
                title=item.title,
                author="",
                content="",
                published_at="",
                tags=(),
                extraction_method="baijiahao_article_page",
                fetch_status="empty",
                raw_payload={"html_length": 0},
            )
        else:
            content = str(payload.get("content", ""))
            detail = ItemDetail(
                item_id=item.item_id,
                platform=item.platform,
                url=item.url,
                title=str(payload.get("title", item.title)),
                author="",
                content=content,
                published_at="",
                tags=(),
                extraction_method=str(payload.get("extraction_method", "baijiahao_article_page")),
                fetch_status=str(payload.get("fetch_status", "success" if content else "empty")),
                raw_payload={"html_length": int(payload.get("html_length", 0) or 0)},
            )
        item_details.append(detail)

    details_by_item_id = {detail.item_id: detail for detail in item_details}

    return _run_platform_pipeline(
        profile_path=profile_path,
        output_root=output_root,
        fetched_at=fetched_at,
        source_id="baidu",
        hot_items_fetcher=lambda _fetched_at: expanded,
        item_detail_fetcher=lambda it: details_by_item_id.get(it.item_id),
        report_renderer=render_baidu_report,
        cache_stats=stats,
    )


def run_bilibili_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    top_n: int = 20,
    offline: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
) -> dict[str, Path]:
    """两段 B站 pipeline：关键词搜专栏 → 专栏正文。"""
    profile = load_user_profile(profile_path)
    fetch = fetcher or _fetch_text_default
    today = utc8_today()
    cache_root_path = Path(cache_root)
    stats = BaiduCacheStats()

    # 对齐 Toutiao：B 站无 board 兜底，core_keywords 为空 → 跳过整个 pipeline
    # （不拉 nav、不跑 search、不抓 article），产出空 hot_items + 空报告。
    if not profile.core_keywords:
        return _run_platform_pipeline(
            profile_path=profile_path,
            output_root=output_root,
            fetched_at=fetched_at,
            source_id="bilibili",
            hot_items_fetcher=lambda _f: [],
            item_detail_fetcher=lambda _it: None,
            report_renderer=render_bilibili_report,
            cache_stats=stats,
        )

    # WBI key（单次 run 拉一次 nav）
    img_key, sub_key = "", ""
    if not offline:
        try:
            img_key, sub_key = img_sub_from_nav(fetch_bilibili_nav(fetch))
        except Exception:
            img_key, sub_key = "", ""

    expanded: list[HotItem] = []
    for word in profile.core_keywords[:top_n]:
        def live_search(_w: str = word) -> list[dict]:
            url = build_search_url(_w, page=1, img_key=img_key, sub_key=sub_key)
            text = fetch_bilibili_search_text(url, fetch)
            items = parse_bilibili_search_response(text, source_word=_w, fetched_at=fetched_at)
            return [
                {"cvid": it.raw_payload["cvid"], "title": it.title, "url": it.url,
                 "views": it.heat.metrics.get("views", 0), "likes": it.heat.metrics.get("likes", 0),
                 "replies": it.heat.metrics.get("replies", 0), "desc": it.summary,
                 "author": it.raw_payload.get("author", ""), "source_word": _w}
                for it in items
            ]

        if force_search_refresh:
            payload, src = bilibili_get_search(cache_root_path, today, word, live_search, force_refresh=True)
        elif offline:
            payload, src = bilibili_get_search(cache_root_path, today, word, live_search, deadline=time.monotonic())
        else:
            payload, src = bilibili_get_search(cache_root_path, today, word, live_search)
        stats.record("search", src, forced=force_search_refresh)
        if not isinstance(payload, list):
            continue
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            cvid = str(entry.get("cvid", "")).strip()
            if not cvid:
                continue
            expanded.append(
                HotItem(
                    item_id=f"bilibili_article_{cvid}",
                    platform="bilibili",
                    item_type="article",
                    title=str(entry.get("title") or word),
                    url=str(entry.get("url", "")),
                    rank=None,
                    heat=HeatMetrics(
                        value=int(entry.get("views", 0) or 0),
                        label=str(entry.get("views", "")),
                        metric_name="article_view",
                        metrics={"views": int(entry.get("views", 0) or 0),
                                 "likes": int(entry.get("likes", 0) or 0),
                                 "replies": int(entry.get("replies", 0) or 0)},
                    ),
                    summary=str(entry.get("desc", "")),
                    category="bilibili_article",
                    matched_query_ids=matched_query_ids,
                    fetched_at=fetched_at,
                    fetch_status="success",
                    raw_payload={"source_kind": "bilibili_search_recall",
                                 "cvid": cvid,
                                 "author": entry.get("author", "")},
                )
            )

    queries = tuple(build_topic_queries(profile))
    matches = [
        result for item in expanded
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]

    item_details: list[ItemDetail] = []
    for match in matches:
        item = match.item
        cvid = str(item.raw_payload.get("cvid", "")).strip()

        def live_article(_cvid: str = cvid, _item=item) -> dict:
            html = fetch_bilibili_article_text(_cvid, fetch)
            detail = parse_bilibili_article_response(
                html, item_id=_item.item_id, item_url=_item.url, fetched_at=fetched_at)
            return {"title": detail.title or _item.title, "content": detail.content,
                    "author": detail.author, "extraction_method": detail.extraction_method,
                    "fetch_status": detail.fetch_status, "html_length": len(html)}

        if force_article_refresh:
            payload, src = bilibili_get_article(cache_root_path, today, cvid, live_article, force_refresh=True)
        elif offline:
            payload, src = bilibili_get_article(cache_root_path, today, cvid, live_article, deadline=time.monotonic())
        else:
            payload, src = bilibili_get_article(cache_root_path, today, cvid, live_article)
        stats.record("article", src, forced=force_article_refresh)
        if not isinstance(payload, dict) or not payload:
            detail = ItemDetail(item_id=item.item_id, platform="bilibili", url=item.url,
                                title=item.title, author="", content="", published_at="",
                                tags=(), extraction_method="bilibili_article_view",
                                fetch_status="empty", raw_payload={"html_length": 0})
        else:
            content = str(payload.get("content", ""))
            detail = ItemDetail(item_id=item.item_id, platform="bilibili", url=item.url,
                                title=str(payload.get("title", item.title)),
                                author=str(payload.get("author", "")), content=content,
                                published_at="", tags=(),
                                extraction_method=str(payload.get("extraction_method", "bilibili_article_view")),
                                fetch_status=str(payload.get("fetch_status", "success" if content else "empty")),
                                raw_payload={"html_length": int(payload.get("html_length", 0) or 0)})
        item_details.append(detail)

    details_by_item_id = {d.item_id: d for d in item_details}
    return _run_platform_pipeline(
        profile_path=profile_path,
        output_root=output_root,
        fetched_at=fetched_at,
        source_id="bilibili",
        hot_items_fetcher=lambda _f: expanded,
        item_detail_fetcher=lambda it: details_by_item_id.get(it.item_id),
        report_renderer=render_bilibili_report,
        cache_stats=stats,
    )


def run_juejin_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int, dict[str, str] | None], str] | None = None,
) -> dict[str, Path]:
    return _run_platform_pipeline(
        profile_path=profile_path,
        output_root=output_root,
        fetched_at=fetched_at,
        source_id="juejin",
        hot_items_fetcher=lambda fetched_at: fetch_juejin_hot_items(
            fetched_at=fetched_at,
            fetcher=fetcher,
        ),
        item_detail_fetcher=lambda item: fetch_juejin_item_detail(
            item,
            fetcher=detail_fetcher,
        ),
        report_renderer=render_juejin_report,
    )


def run_juejin_pipeline_v2(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int, dict | None], str] | None = None,
    detail_fetcher: Callable[[str, int, dict | None], str] | None = None,
    top_n: int = 20,
    offline: bool = False,
    force_rank_refresh: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
    min_hot_board_before_search: int = 5,  # 对齐 Toutiao PathFilters.min_hot_board_before_search
) -> dict[str, Path]:
    """三段掘金 v2：hot-rank + 关键词搜索合并去重 → 正文。

    对齐 Toutiao Path A/B 模式：
      - rank 中匹配 persona 的条目 = Path A；关键词搜索 = Path B。
      - Path A 命中数 ≥ min_hot_board_before_search 或 core_keywords 为空 → 跳过 search。
      - 按 article_id 去重，rank 命中优先保留 source_path=A；输出顺序 A 在前 → B 在后。
    """
    profile = load_user_profile(profile_path)
    fetch = fetcher
    detail_fetch = detail_fetcher or fetcher
    today = utc8_today()
    cache_root_path = Path(cache_root)
    stats = BaiduCacheStats()
    search_items: list[HotItem] = []  # 阈值门控或空 keywords 时保持为空

    # ---- stage 1: hot-rank（date key，映射到 board 统计层）----
    from heated_topics_v3.providers.juejin import JUEJIN_HOT_RANK_URL

    def live_rank(_date: str) -> dict:
        return {"response_text": fetch(JUEJIN_HOT_RANK_URL, 20, None)}

    if force_rank_refresh:
        rank_payload, src = juejin_get_rank(cache_root_path, today, live_rank, force_refresh=True)
    elif offline:
        rank_payload, src = juejin_get_rank(cache_root_path, today, live_rank, deadline=time.monotonic())
    else:
        rank_payload, src = juejin_get_rank(cache_root_path, today, live_rank)
    stats.record("board", src, forced=force_rank_refresh)
    rank_text = str(rank_payload.get("response_text", "")) if isinstance(rank_payload, dict) else ""
    rank_items = parse_juejin_rank_response(rank_text, fetched_at=fetched_at,
                                            matched_query_ids=matched_query_ids) if rank_text.strip() else []

    # ---- 对齐 Toutiao：Path A 阈值门控 ----
    # 先用 persona 查询对 rank_items 做一次匹配，统计 Path A 命中数；
    # 若 ≥ min_hot_board_before_search → 跳过 search 阶段。
    queries_for_gate = tuple(build_topic_queries(profile))
    path_a_items = [
        item for item in rank_items
        if match_hot_item_to_queries(item, queries_for_gate, profile.excluded_keywords).is_relevant
    ]
    skip_search = (len(path_a_items) >= min_hot_board_before_search) or (not profile.core_keywords)

    if not skip_search:
        # ---- stage 2: 关键词搜索（word key）----
        search_items = []
        for word in profile.core_keywords[:top_n]:
            def live_search(_w: str = word) -> list[dict]:
                items = fetch_juejin_search_items(_w, fetched_at=fetched_at, fetcher=fetch)
                return [{"article_id": it.item_id.replace("juejin_", ""), "title": it.title,
                         "views": it.heat.metrics.get("views", 0), "likes": it.heat.metrics.get("likes", 0),
                         "collects": it.heat.metrics.get("collects", 0), "comments": it.heat.metrics.get("comments", 0),
                         "summary": it.summary} for it in items]

            if force_search_refresh:
                payload, s = juejin_get_search(cache_root_path, today, word, live_search, force_refresh=True)
            elif offline:
                payload, s = juejin_get_search(cache_root_path, today, word, live_search, deadline=time.monotonic())
            else:
                payload, s = juejin_get_search(cache_root_path, today, word, live_search)
            stats.record("search", s, forced=force_search_refresh)
            if not isinstance(payload, list):
                continue
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                aid = str(entry.get("article_id", "")).strip()
                title = str(entry.get("title", "")).strip()
                if not aid or not title:
                    continue
                search_items.append(HotItem(
                    item_id=f"juejin_{aid}", platform="juejin", item_type="article", title=title,
                    url=f"https://juejin.cn/post/{aid}", rank=None,
                    heat=HeatMetrics(value=None, label="", metric_name="search_recall", metrics={
                        "views": int(entry.get("views", 0) or 0), "likes": int(entry.get("likes", 0) or 0),
                        "collects": int(entry.get("collects", 0) or 0), "comments": int(entry.get("comments", 0) or 0)}),
                    summary=str(entry.get("summary", "")), category="",
                    matched_query_ids=matched_query_ids, fetched_at=fetched_at, fetch_status="success",
                    raw_payload={"content": {"content_id": aid},
                                 "source_kind": "juejin_search_recall",
                                 "source_path": "B"}))  # 对齐 Toutiao：search 标 B

    # ---- 合并去重：rank 优先，保留 source_path=A；order: rank-first → search-not-in-rank ----
    merged = merge_juejin_items(rank_items, search_items if not skip_search else [])

    # ---- matching ----
    queries = tuple(build_topic_queries(profile))
    matches = [result for item in merged
               if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant]

    # ---- stage 3: 正文（id key，复用 fetch_juejin_item_detail）----
    item_details: list[ItemDetail] = []
    for match in matches:
        item = match.item
        aid = item.item_id.replace("juejin_", "")

        def live_article(_aid: str = aid, _item=item) -> dict:
            detail = fetch_juejin_item_detail(_item, fetcher=detail_fetch)
            return {"title": detail.title, "content": detail.content, "author": detail.author,
                    "published_at": detail.published_at, "extraction_method": detail.extraction_method,
                    "fetch_status": detail.fetch_status}

        if force_article_refresh:
            payload, s = juejin_get_article(cache_root_path, today, aid, live_article, force_refresh=True)
        elif offline:
            payload, s = juejin_get_article(cache_root_path, today, aid, live_article, deadline=time.monotonic())
        else:
            payload, s = juejin_get_article(cache_root_path, today, aid, live_article)
        stats.record("article", s, forced=force_article_refresh)
        if not isinstance(payload, dict) or not payload:
            detail = ItemDetail(item_id=item.item_id, platform="juejin", url=item.url, title=item.title,
                                author="", content="", published_at="", tags=(),
                                extraction_method="juejin_detail_api", fetch_status="empty", raw_payload={})
        else:
            detail = ItemDetail(item_id=item.item_id, platform="juejin", url=item.url,
                                title=str(payload.get("title", item.title)), author=str(payload.get("author", "")),
                                content=str(payload.get("content", "")), published_at=str(payload.get("published_at", "")),
                                tags=(), extraction_method=str(payload.get("extraction_method", "juejin_detail_api")),
                                fetch_status=str(payload.get("fetch_status", "success")), raw_payload={})
        item_details.append(detail)

    details_by_item_id = {d.item_id: d for d in item_details}
    return _run_platform_pipeline(
        profile_path=profile_path, output_root=output_root, fetched_at=fetched_at, source_id="juejin",
        hot_items_fetcher=lambda _f: merged,
        item_detail_fetcher=lambda it: details_by_item_id.get(it.item_id),
        report_renderer=render_juejin_report_v2, cache_stats=stats)


def run_toutiao_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int], str] | None = None,
) -> dict[str, Path]:
    profile = load_user_profile(profile_path)
    queries = tuple(build_topic_queries(profile))
    phrases = build_toutiao_search_phrases(queries)
    hot_board_items = fetch_toutiao_hot_items(fetched_at=fetched_at, fetcher=fetcher)
    search_results = fetch_toutiao_search_items(
        phrases=phrases,
        fetched_at=fetched_at,
        fetcher=fetcher,
    )
    hot_items = merge_toutiao_items(search_results, hot_board_items)
    matches = [
        result
        for item in hot_items
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]
    item_details = fetch_toutiao_item_details(
        [match.item for match in matches],
        fetcher=detail_fetcher,
    )

    output_dir = _run_output_dir(output_root, profile.profile_id, "toutiao", fetched_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    article_texts_dir = output_dir / "article_texts"
    hot_items_path = output_dir / "hot_items.json"
    report_path = output_dir / "report.md"
    hot_item_rows = _build_hot_item_rows(matches, item_details, article_texts_dir)

    _write_json(hot_items_path, hot_item_rows)
    report_path.write_text(
        render_toutiao_report(profile, matches, fetched_at, item_details),
        encoding="utf-8",
    )

    return {
        "article_texts": article_texts_dir,
        "hot_items": hot_items_path,
        "report": report_path,
    }


def _run_platform_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    source_id: str,
    hot_items_fetcher,
    item_detail_fetcher,
    report_renderer,
    cache_stats=None,
) -> dict[str, Path]:
    profile = load_user_profile(profile_path)
    queries = tuple(build_topic_queries(profile))
    hot_items = hot_items_fetcher(fetched_at)
    matches = [
        result
        for item in hot_items
        if (result := match_hot_item_to_queries(item, queries, profile.excluded_keywords)).is_relevant
    ]
    item_details = [
        item_detail_fetcher(match.item)
        for match in matches
    ]

    output_dir = _run_output_dir(output_root, profile.profile_id, source_id, fetched_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    article_texts_dir = output_dir / "article_texts"
    hot_items_path = output_dir / "hot_items.json"
    report_path = output_dir / "report.md"
    hot_item_rows = _build_hot_item_rows(matches, item_details, article_texts_dir)

    _write_json(hot_items_path, hot_item_rows)
    report_path.write_text(
        report_renderer(profile, matches, fetched_at, item_details, cache_stats=cache_stats),
        encoding="utf-8",
    )

    return {
        "article_texts": article_texts_dir,
        "hot_items": hot_items_path,
        "report": report_path,
    }


def _build_hot_item_rows(
    matches: list[MatchResult],
    item_details: list[ItemDetail],
    article_texts_dir: Path,
) -> list[dict[str, object]]:
    article_texts_dir.mkdir(parents=True, exist_ok=True)
    details_by_item_id = {detail.item_id: detail for detail in item_details}
    rows: list[dict[str, object]] = []
    for index, match in enumerate(matches, start=1):
        item = match.item
        detail = details_by_item_id.get(item.item_id)
        txt_path = ""
        content_chars = 0
        fetch_status = "not_fetched"
        extraction_method = ""
        if detail is not None:
            filename = f"{index:03d}_{_safe_filename(detail.title or item.title)}.txt"
            absolute_txt_path = article_texts_dir / filename
            relative_txt_path = Path("article_texts") / filename
            _write_article_text(absolute_txt_path, detail)
            txt_path = relative_txt_path.as_posix()
            content_chars = len(detail.content)
            fetch_status = detail.fetch_status
            extraction_method = detail.extraction_method
        rows.append(
            {
                "item": item,
                "match_terms": match.match_terms,
                "excluded_terms": match.excluded_terms,
                "relevance_score": match.relevance_score,
                "detail": {
                    "fetch_status": fetch_status,
                    "extraction_method": extraction_method,
                    "txt_path": txt_path,
                    "content_chars": content_chars,
                },
            }
        )
    return rows


def _write_article_text(path: Path, detail: ItemDetail) -> None:
    body = "\n".join(
        [
            f"Title: {detail.title}",
            f"Platform: {detail.platform}",
            f"Author: {detail.author}",
            f"Published at: {detail.published_at}",
            f"Fetch status: {detail.fetch_status}",
            f"Extraction method: {detail.extraction_method}",
            "",
            "Content:",
            detail.content,
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")


def _safe_filename(value: str) -> str:
    safe = "".join("_" if char in '<>:"/\\|?*' else char for char in value.strip())
    safe = " ".join(safe.split())
    safe = safe.strip(". ")
    return (safe or "article")[:100]


def load_user_profile(profile_path: Path) -> UserProfile:
    payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    return UserProfile(
        profile_id=str(payload["profile_id"]),
        display_name=str(payload["display_name"]),
        domains=tuple(payload.get("domains", [])),
        audience=tuple(payload.get("audience", [])),
        content_modes=tuple(payload.get("content_modes", [])),
        preferred_platforms=tuple(payload.get("preferred_platforms", [])),
        core_keywords=tuple(payload.get("core_keywords", [])),
        entity_keywords=tuple(payload.get("entity_keywords", [])),
        excluded_keywords=tuple(payload.get("excluded_keywords", [])),
    )


def _write_json(path: Path, rows: object) -> None:
    path.write_text(
        json.dumps(to_plain_data(rows), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_output_dir(output_root: Path, profile_id: str, source_id: str, fetched_at: str) -> Path:
    timestamp = fetched_at.replace("-", "").replace(":", "").split("+", maxsplit=1)[0]
    timestamp = timestamp.replace("T", "_")
    return output_root / profile_id / source_id / f"run_{timestamp}"


# ---------------------------------------------------------------------------
# Toutiao v2 pipeline (persona-driven, daily hot board cache, per-user output)
# ---------------------------------------------------------------------------


def run_toutiao_pipeline_v2(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    hot_board_cache_root: Path = Path("cache"),
    persona_keyword_cache_root: Path = Path("cache/core_keywords"),
    force_hot_board_refresh: bool = False,
    allow_yesterday_fallback: bool = True,
    offline: bool = False,
    top_n: int = 10,
    path_filters: PathFilters = PathFilters(),
    fetcher: Callable[[str, int], str] | None = None,
    article_info_fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int], str] | None = None,
    rendered_text_fetcher: Callable[[str, int], str] | None = None,
    custom_keywords: tuple[str, ...] = (),
    on_search_committed: Callable[[], None] | None = None,
    search_phase_budget_seconds: float = 20.0,
    _monotonic: Callable[[], float] = time.monotonic,
) -> "ToutiaoV2Result":
    """Persona-driven Toutiao pipeline.

    Steps:
      1. Load + validate v2 profile.
      2. Build keywords from profile.core_keywords or custom_keywords.
      3. Read/write daily hot board cache.
      4. Per-keyword search, enrich with mobile article info.
      5. Build candidates via Paths A/B/C and rank by heat.
      6. Sort + slice top_n.
      7. Fetch item details for kept candidates.
      8. Render Markdown report.
      9. Write per-user per-date run directory.
    """
    if is_legacy_profile(profile_path):
        raise ValueError(
            f"{profile_path} uses legacy v1 schema; please migrate to v2 "
            "(see heated_topics_v3.profile_loader.migrate_v1_to_v2)"
        )

    profile = load_persona_profile(profile_path)
    if custom_keywords:
        extraction = PersonaKeywordExtraction(
            user_id=profile.user_id,
            persona_signature=profile.persona_signature,
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in custom_keywords),
            source="custom",
        )
    else:
        # Use profile.core_keywords directly (keywords were pre-generated via refresh-keywords)
        extraction = PersonaKeywordExtraction(
            user_id=profile.user_id,
            persona_signature=profile.persona_signature,
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in profile.core_keywords),
            source="core_keywords",
        )

    date = utc8_today()
    # Smart hot board fetch: if offline but today's cache missing, auto-refresh
    _cache_path = hot_board_cache_path(hot_board_cache_root, date)
    _today_cached = _cache_path.exists()
    if offline and not _today_cached:
        # offline but no cache → upgrade to auto-refresh
        hot_board_snapshot, source_label = get_or_fetch_hot_board(
            hot_board_cache_root, date,
            fetcher=fetcher,
            force_refresh=True,
            allow_yesterday_fallback=allow_yesterday_fallback,
        )
    elif offline:
        hot_board_snapshot, source_label = get_or_fetch_hot_board(
            hot_board_cache_root, date,
            fetcher=None,
            force_refresh=False,
            allow_yesterday_fallback=True,
        )
    else:
        hot_board_snapshot, source_label = get_or_fetch_hot_board(
            hot_board_cache_root, date,
            fetcher=fetcher,
            force_refresh=force_hot_board_refresh,
            allow_yesterday_fallback=allow_yesterday_fallback,
        )

    keyword_phrases = tuple(k.keyword for k in extraction.keywords)

    if custom_keywords:
        persona_keywords = keyword_phrases
    else:
        persona_keywords = profile.core_keywords + keyword_phrases

    hot_board_only = build_hot_board_candidates(
        hot_board=list(hot_board_snapshot.items),
        persona_keywords=persona_keywords,
        filters=path_filters,
    )
    skip_search = (
        len(hot_board_only) >= path_filters.min_hot_board_before_search
        or not keyword_phrases
    )

    raw_search_by_keyword: dict[str, list] = {}
    enriched_search_by_keyword: dict[str, list] = {}
    article_info_by_url: dict[str, dict] = {}
    if not skip_search:
        search_pages = path_filters.search_pages or 1
        search_deadline = _monotonic() + max(0.0, search_phase_budget_seconds)
        for index, keyword in enumerate(keyword_phrases):
            if _monotonic() >= search_deadline:
                for skipped_keyword in keyword_phrases[index:]:
                    raw_search_by_keyword[skipped_keyword] = []
                break
            try:
                results, _search_source = get_or_fetch_search_items(
                    hot_board_cache_root,
                    date,
                    keyword,
                    search_pages,
                    path_filters.per_page,
                    fetched_at,
                    lambda remaining_seconds, keyword=keyword: fetch_toutiao_search_pages(
                        keyword,
                        fetched_at=fetched_at,
                        max_pages=search_pages,
                        per_page=path_filters.per_page,
                        fetcher=fetcher,
                        timeout_seconds=max(1, math.ceil(remaining_seconds)),
                    ),
                    deadline=search_deadline,
                    monotonic=_monotonic,
                )
            except Exception:
                results = []
            raw_search_by_keyword[keyword] = results

        seen_article_ids: set[str] = set()
        for keyword, items in raw_search_by_keyword.items():
            enriched: list = []
            for item in items:
                resolved_url = resolve_toutiao_content_url(item.url)
                aid = extract_toutiao_article_id(resolved_url)
                info = None
                if aid and aid not in seen_article_ids:
                    info = fetch_toutiao_article_info(aid, fetcher=article_info_fetcher)
                    if info is not None:
                        seen_article_ids.add(aid)
                enriched_item = attach_article_heat_fields(item, info)
                enriched.append(enriched_item)
                canonical = _canonical_url(enriched_item.url)
                article_info_by_url[canonical] = {
                    "impression_count": _safe_int(info, "impression_count") if info else None,
                    "digg_count": _safe_int(info, "digg_count") if info else None,
                    "comment_count": _safe_int(info, "comment_count") if info else None,
                    "repost_count": _safe_int(info, "repost_count") if info else None,
                    "repin_count": _safe_int(info, "repin_count") if info else None,
                    "is_toutiao_hot": bool(info and info.get("is_toutiao_hot")),
                    "article_heat": int(raw_payload_get(enriched_item.raw_payload, "article_heat", 0) or 0),
                }
            enriched_search_by_keyword[keyword] = enriched

    if skip_search:
        candidates = hot_board_only
    else:
        candidates = build_candidates(
            hot_board=list(hot_board_snapshot.items),
            keywords=extraction.keywords,
            persona_keywords=persona_keywords,
            search_results_by_keyword=enriched_search_by_keyword,
            article_info_by_url=article_info_by_url,
            filters=path_filters,
        )

    candidates = select_search_candidates_by_heat(candidates)

    # Fallback: if candidates < top_n, supplement with all search results sorted by heat
    if len(candidates) < top_n:
        all_search_candidates = _all_search_candidates(enriched_search_by_keyword, persona_keywords)
        for c in all_search_candidates:
            if c not in candidates:
                candidates.append(c)

    candidates.sort(key=lambda c: as_sort_key(hybrid_score_v2(c.item, persona_keywords)))
    top_candidates = candidates[: max(0, top_n)]

    top_candidates = _enrich_top_path_a_candidates(top_candidates, article_info_fetcher)

    detail_fetcher_eff = detail_fetcher
    item_details = fetch_toutiao_item_details(
        [c.item for c in top_candidates],
        fetcher=detail_fetcher_eff,
        rendered_texts_fetcher=(
            None
            if detail_fetcher_eff is not None
            else (lambda urls, t: _rendered_texts(urls, t, rendered_text_fetcher))
        ),
    )

    report_md = render_toutiao_report_v2(
        profile,
        extraction,
        top_candidates,
        fetched_at=fetched_at,
        item_details=item_details,
    )

    run_result = write_toutiao_run(
        user_id=profile.user_id,
        date=date,
        candidates=candidates,
        top_n=top_n,
        hot_board_snapshot=hot_board_snapshot,
        raw_search_by_keyword=enriched_search_by_keyword,
        raw_article_info_by_url=article_info_by_url,
        item_details=item_details,
        report_markdown=report_md,
        output_root=output_root,
        hot_board_cache_root=hot_board_cache_root,
    )

    if on_search_committed is not None and not skip_search:
        on_search_committed()

    return ToutiaoV2Result(
        user_id=profile.user_id,
        date=date,
        run_dir=run_result.run_dir,
        top_n=top_n,
        candidates_total=len(candidates),
        kept_total=len(top_candidates),
        paths=run_result.paths,
        hot_board_source=source_label,
        keyword_source=extraction.source,
        keyword_count=len(extraction.keywords),
        report_path=run_result.run_dir / "report.md",
        focused_path=run_result.run_dir / "focused.json",
    )


def _all_search_candidates(
    enriched_search_by_keyword: dict[str, list],
    persona_keywords: tuple[str, ...],
) -> list["Candidate"]:
    """Collect ALL search results as candidates, sorted by heat desc."""
    all_items: list[HotItem] = []
    for items in enriched_search_by_keyword.values():
        all_items.extend(items)

    candidates: list[Candidate] = []
    seen_keys: set[str] = set()
    for item in all_items:
        resolved = resolve_toutiao_content_url(item.url)
        article_id = extract_toutiao_article_id(resolved)
        key = f"aid:{article_id}" if article_id else f"url:{_canonical_url(item.url)}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        scored = hybrid_score_v2(item, persona_keywords)
        info_raw = item.raw_payload or {}
        is_th = bool(info_raw.get("is_toutiao_hot"))
        candidates.append(Candidate(
            item=item,
            source_path=PATH_B,
            matched_keyword=info_raw.get("matched_keyword") or None,
            is_toutiao_hot=is_th,
            is_hot_board=False,
            persona_matched=scored.persona_matched,
            preliminary_score=scored.score,
        ))

    def heat_of(c: Candidate) -> int:
        return int((c.item.raw_payload or {}).get("article_heat", 0) or 0)

    candidates.sort(key=heat_of, reverse=True)
    return candidates


def _enrich_top_path_a_candidates(
    candidates: list["Candidate"],
    article_info_fetcher: Callable[[str, int], str] | None,
) -> list["Candidate"]:
    """Fill in ``content_html`` for Path A hot-board candidates.

    Path A items never go through ``attach_article_heat_fields`` in the search
    loop, so ``raw_payload.content_html`` stays empty. When the desktop HTML
    page is JS-rendered (the common case for hot-board trending items),
    ``parse_toutiao_article_page`` returns ``fetch_status="empty"`` and
    ``_partial_detail`` falls back to ``content_html`` — which is also empty —
    leaving the article file body blank. Calling ``fetch_toutiao_article_info``
    for these top candidates restores the fallback.

    Path A items already keep their ``hot_value`` (see
    ``attach_article_heat_fields``: ``was_hot_board`` branch), so this does
    not perturb the candidate's preliminary score. When ``article_info_fetcher``
    is None, ``fetch_toutiao_article_info`` falls back to plain ``urllib`` —
    matching how Path B enrichment behaves for the same parameter.
    """
    enriched: list["Candidate"] = []
    for candidate in candidates:
        if not candidate.is_hot_board:
            enriched.append(candidate)
            continue
        item = candidate.item
        if item.raw_payload.get("article_info_status") == "ok":
            enriched.append(candidate)
            continue
        resolved = resolve_toutiao_content_url(item.url)
        article_id = extract_toutiao_article_id(resolved)
        if not article_id:
            enriched.append(candidate)
            continue
        info = fetch_toutiao_article_info(article_id, fetcher=article_info_fetcher)
        new_item = attach_article_heat_fields(item, info)
        enriched.append(replace(candidate, item=new_item))
    return enriched


@dataclass(frozen=True)
class ToutiaoV2Result:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str
    keyword_source: str
    keyword_count: int
    report_path: Path
    focused_path: Path


def _canonical_url(url: str) -> str:
    return url.split("?", maxsplit=1)[0]


def _safe_int(info: dict | None, key: str) -> int | None:
    if not info:
        return None
    value = info.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def raw_payload_get(payload: dict, key: str, default=None):
    return payload.get(key, default)


def _rendered_texts(urls, timeout_seconds, fetcher):
    if fetcher is None:
        return {}
    return {url: fetcher(url, timeout_seconds) for url in urls}


@dataclass(frozen=True)
class SinaNewsV2Result:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str
    keyword_source: str  # "core_keywords"
    keyword_count: int
    report_path: Path
    focused_path: Path


def _sina_score_item(
    item: HotItem, persona_keywords: tuple[str, ...]
) -> "NewsScore":
    """Wrap ``hybrid_score_v2`` so the shared builder can score Sina items.

    Sina items get ``source_kind="hot_board"`` injected by the pipeline on
    board rows so ``hybrid_score_v2`` can apply the hot-board log10 base;
    search items keep their empty ``source_kind`` and use the search offset.
    """
    from heated_topics_v3.news_pipeline_paths import NewsScore
    scored = hybrid_score_v2(item, persona_keywords)
    return NewsScore(
        score=scored.score,
        persona_matched=scored.persona_matched,
        is_toutiao_hot=scored.is_toutiao_hot,
    )


def _write_news_article_text(path: Path, candidate: "Candidate", detail: ItemDetail) -> None:
    """Generic article text used by sina/netease v2 (no hot board snapshot)."""
    raw_payload = candidate.item.raw_payload
    heat_line = (
        f"HotValue: {candidate.item.heat.value}"
        if candidate.is_hot_board
        else "HotValue: n/a (search result)"
    )
    body = "\n".join([
        f"Title: {detail.title}",
        f"Keyword: {candidate.matched_keyword or 'n/a'}",
        f"Source path: {candidate.source_path}",
        f"Fetched at: {detail.raw_payload.get('fetched_at') or candidate.item.fetched_at}",
        heat_line,
        f"is_toutiao_hot: {candidate.is_toutiao_hot}",
        "",
        "=" * 60,
        detail.content,
        "",
    ])
    path.write_text(body, encoding="utf-8")


def _fetch_news_article_details(
    *,
    kept_candidates: list["Candidate"],
    cache_root_path: Path,
    date: str,
    offline: bool,
    force_article_refresh: bool,
    stats: "BaiduCacheStats",
    fetcher: Callable[[str, int], str],
    dedup_key_fn: Callable[[HotItem], str],
    platform: str,
    parser: Callable[[str, str, str], str],
    extraction_method: str,
    article_getter: Callable,
) -> list[ItemDetail]:
    """Fetch each kept candidate's article body through the v2 cache layer.

    Returns an ``ItemDetail`` per kept candidate. Failed fetches (HTTPError,
    URLError, OSError) and parser failures (ValueError, TypeError) collapse
    to an empty-content row with ``fetch_status="empty"`` — never aborting
    the run for a single upstream 404.
    """
    item_details: list[ItemDetail] = []
    for candidate in kept_candidates:
        item = candidate.item
        cache_key = dedup_key_fn(item)

        def live_article(_aid: str = cache_key, _item=item) -> dict:
            try:
                html = fetcher(_item.url, 20)
            except (urllib.error.HTTPError, urllib.error.URLError, OSError):
                return {"title": _item.title, "content": "",
                        "extraction_method": extraction_method,
                        "fetch_status": "empty", "html_length": 0}
            try:
                content = parser(html, title=_item.title, summary="")
            except (ValueError, TypeError):
                content = ""
            return {"title": _item.title, "content": content,
                    "extraction_method": extraction_method,
                    "fetch_status": "success" if content else "empty",
                    "html_length": len(html)}

        payload, src = _news_cache_get_article(
            article_getter,
            cache_root_path, date, cache_key, live_article,
            offline=offline, force_refresh=force_article_refresh,
        )
        stats.record("article", src, forced=force_article_refresh)
        if not isinstance(payload, dict) or not payload:
            detail = ItemDetail(item_id=item.item_id, platform=platform, url=item.url,
                                title=item.title, author="", content="",
                                published_at="", tags=(),
                                extraction_method=extraction_method,
                                fetch_status="empty", raw_payload={"html_length": 0})
        else:
            content = str(payload.get("content", ""))
            detail = ItemDetail(item_id=item.item_id, platform=platform, url=item.url,
                                title=str(payload.get("title", item.title)),
                                author="", content=content, published_at="",
                                tags=(),
                                extraction_method=str(payload.get("extraction_method", extraction_method)),
                                fetch_status=str(payload.get("fetch_status",
                                                              "success" if content else "empty")),
                                raw_payload={"html_length": int(payload.get("html_length", 0) or 0)})
        item_details.append(detail)
    return item_details


def run_sina_news_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    top_n: int = 10,
    offline: bool = False,
    force_board_refresh: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
    custom_keywords: tuple[str, ...] = (),
    on_search_committed: Callable[[], None] | None = None,
    path_filters: PathFilters = PathFilters(
        hot_board_min=1000,
        article_heat_min=0,
        min_hot_board_before_search=3,
        include_is_toutiao_hot_fallback=False,
    ),
) -> "SinaNewsV2Result":
    """Sina News v2 pipeline: hot board → per-keyword search → per-article body.

    Mirrors the Toutiao v2 architecture (shared ``build_news_candidates`` +
    ``write_news_run``) but with Sina-specific scoring, dedup, and Path A
    defaults (``hot_board_min=1000`` instead of Toutiao's 1M).
    """
    from heated_topics_v3.news_cache import (
        get_or_fetch_sina_news_article_with_record,
        get_or_fetch_sina_news_board_with_record,
        get_or_fetch_sina_news_search_with_record,
    )
    from heated_topics_v3.news_pipeline_paths import NewsPathContext, build_news_candidates
    from heated_topics_v3.news_pipeline_output import (
        NewsOutputContext,
        write_news_run,
    )
    from heated_topics_v3.providers.sina_news import (
        SINA_HOT_URL, SINA_SEARCH_URL,
        parse_sina_article_response,
        parse_sina_hot_response,
        parse_sina_search_response,
    )
    from heated_topics_v3.reporting import render_sina_news_report_v2

    profile = load_user_profile(profile_path)
    fetch = fetcher or _fetch_text_default
    today = utc8_today()
    cache_root_path = Path(cache_root)
    stats = BaiduCacheStats()

    # ---- stage 1: hot board (Path A) ----
    def live_board(_date: str) -> dict:
        return {"response_text": fetch(SINA_HOT_URL, 20)}

    board_payload, board_src = _news_cache_get(
        get_or_fetch_sina_news_board_with_record,
        cache_root_path, today, live_board,
        offline=offline, force_refresh=force_board_refresh,
    )
    stats.record("board", board_src, forced=force_board_refresh)
    board_text = str(board_payload.get("response_text", "")) if isinstance(board_payload, dict) else ""
    try:
        raw_board_items = parse_sina_hot_response(
            board_text, fetched_at=fetched_at) if board_text.strip() else []
    except ValueError:
        raw_board_items = []

    # Sina board items do not carry ``source_kind`` — inject it so
    # ``hybrid_score_v2`` recognizes them as hot-board rows and applies the
    # log10 base + boost rather than the search offset.
    board_items: list[HotItem] = []
    for it in raw_board_items:
        merged_payload = {**it.raw_payload, "source_kind": "hot_board"}
        board_items.append(replace(it, raw_payload=merged_payload))

    # ---- keywords — hard cap at 5 ----
    if custom_keywords:
        keywords = tuple(k.strip() for k in custom_keywords if k.strip())[:5]
        source = "custom"
    else:
        keywords = tuple(w.strip() for w in profile.core_keywords if w.strip())[:5]
        source = "core_keywords"
    extraction = PersonaKeywordExtraction(
        user_id=profile.profile_id,
        persona_signature="",
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
        source=source,
    )
    persona_keywords = tuple(keywords)

    # ---- stage 2: per-keyword search (Path B) ----
    raw_search_by_keyword: dict[str, list[HotItem]] = {}
    article_info_by_key: dict[str, dict] = {}
    for word in keywords:
        def live_search(_w: str = word) -> list[dict]:
            from urllib.parse import urlencode
            url = f"{SINA_SEARCH_URL}?{urlencode({'q': _w, 'range': 'all'})}"
            items = parse_sina_search_response(fetch(url, 20), fetched_at=fetched_at)
            # ``dataid`` carries a channel prefix (e.g. ``comos:``); strip it
            # to the bare id so Path B is keyed the same as Path A's ``ext4``.
            return [
                {"article_id": _sina_bare_id(it.raw_payload) or it.item_id,
                 "title": it.title, "url": it.url}
                for it in items
            ]

        payload, src = _news_cache_get_search(
            get_or_fetch_sina_news_search_with_record,
            cache_root_path, today, word, live_search,
            offline=offline, force_refresh=force_search_refresh,
        )
        stats.record("search", src, forced=force_search_refresh)
        if not isinstance(payload, list):
            raw_search_by_keyword[word] = []
            continue
        items: list[HotItem] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("url", "")).strip()
            article_id = str(entry.get("article_id", "")).strip()
            if not title or not url or not article_id:
                continue
            item = HotItem(
                item_id=f"sina_news_{article_id}", platform="sina_news",
                item_type="news", title=title, url=url, rank=None,
                heat=HeatMetrics(value=None, label="", metric_name="search_rank", metrics={}),
                summary=title, category="", matched_query_ids=matched_query_ids,
                fetched_at=fetched_at, fetch_status="success",
                raw_payload={"source_kind": "sina_news_search_recall",
                             "article_id": article_id},
            )
            items.append(item)
            # Sina has no per-article heat / is_toutiao_hot — populate with
            # neutral defaults so Path B's ``article_heat_min`` filter doesn't
            # drop valid search hits.
            article_info_by_key[article_id] = {"article_heat": 0, "is_toutiao_hot": False}
        raw_search_by_keyword[word] = items

    # ---- build candidates via the shared Path A/B/C builder ----
    ctx = NewsPathContext(
        identity_key=_sina_news_dedup_key,
        enrich_with_article_info=lambda item, _info: item,
        score_item=_sina_score_item,
    )
    candidates = build_news_candidates(
        hot_board=list(board_items),
        keywords=extraction.keywords,
        persona_keywords=persona_keywords,
        search_results_by_keyword=raw_search_by_keyword,
        article_info_by_key=article_info_by_key,
        filters=path_filters,
        ctx=ctx,
    )
    candidates = select_search_candidates_by_heat(candidates)
    candidates.sort(key=lambda c: as_sort_key(hybrid_score_v2(c.item, persona_keywords)))

    kept_candidates = candidates[: max(0, top_n)]

    # ---- stage 3: per-article body ----
    item_details = _fetch_news_article_details(
        kept_candidates=kept_candidates,
        cache_root_path=cache_root_path,
        date=today,
        offline=offline,
        force_article_refresh=force_article_refresh,
        stats=stats,
        fetcher=fetch,
        dedup_key_fn=_sina_news_dedup_key,
        platform="sina_news",
        parser=parse_sina_article_response,
        extraction_method="sina_news_article_page",
        article_getter=get_or_fetch_sina_news_article_with_record,
    )

    # ---- report + output ----
    report_md = render_sina_news_report_v2(
        profile, extraction, kept_candidates, fetched_at,
        item_details=item_details, cache_stats=stats,
    )
    run_result = write_news_run(
        user_id=profile.profile_id,
        date=today,
        candidates=candidates,
        top_n=top_n,
        raw_search_by_keyword=raw_search_by_keyword,
        raw_article_info_by_key=article_info_by_key,
        item_details=item_details,
        report_markdown=report_md,
        ctx=NewsOutputContext(
            canonical_url=_canonical_url,
            write_article_text=_write_news_article_text,
            fetched_at=fetched_at,
        ),
        output_root=output_root,
    )

    if on_search_committed is not None and raw_search_by_keyword:
        on_search_committed()

    return SinaNewsV2Result(
        user_id=profile.profile_id,
        date=today,
        run_dir=run_result.run_dir,
        top_n=top_n,
        candidates_total=run_result.candidates_total,
        kept_total=run_result.kept_total,
        paths=run_result.paths,
        hot_board_source=board_src,
        keyword_source=extraction.source,
        keyword_count=len(extraction.keywords),
        report_path=run_result.run_dir / "report.md",
        focused_path=run_result.run_dir / "focused.json",
    )


@dataclass(frozen=True)
class NeteaseNewsV2Result:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str
    keyword_source: str  # "core_keywords"
    keyword_count: int
    report_path: Path
    focused_path: Path


def _netease_score_item(
    item: HotItem, persona_keywords: tuple[str, ...]
) -> "NewsScore":
    """Wrap ``hybrid_score_v2`` for shared NetEase candidate scoring."""
    from heated_topics_v3.news_pipeline_paths import NewsScore
    scored = hybrid_score_v2(item, persona_keywords)
    return NewsScore(
        score=scored.score,
        persona_matched=scored.persona_matched,
        is_toutiao_hot=scored.is_toutiao_hot,
    )


def run_netease_news_pipeline(
    profile_path: Path,
    output_root: Path,
    fetched_at: str,
    *,
    cache_root: Path,
    fetcher: Callable[[str, int], str] | None = None,
    top_n: int = 10,
    offline: bool = False,
    force_board_refresh: bool = False,
    force_search_refresh: bool = False,
    force_article_refresh: bool = False,
    matched_query_ids: tuple[str, ...] = (),
    custom_keywords: tuple[str, ...] = (),
    on_search_committed: Callable[[], None] | None = None,
    path_filters: PathFilters = PathFilters(
        hot_board_min=1000,
        article_heat_min=0,
        min_hot_board_before_search=3,
        include_is_toutiao_hot_fallback=False,
    ),
) -> "NeteaseNewsV2Result":
    """NetEase News v2 pipeline: board + search candidates → article bodies."""
    from heated_topics_v3.news_cache import (
        get_or_fetch_netease_news_article_with_record,
        get_or_fetch_netease_news_board_with_record,
        get_or_fetch_netease_news_search_with_record,
    )
    from heated_topics_v3.news_pipeline_output import NewsOutputContext, write_news_run
    from heated_topics_v3.news_pipeline_paths import NewsPathContext, build_news_candidates
    from heated_topics_v3.providers.netease_news import (
        NETEASE_HOT_URL,
        NETEASE_SEARCH_URL,
        parse_netease_article_response,
        parse_netease_hot_response,
        parse_netease_search_response,
    )
    from heated_topics_v3.reporting import render_netease_news_report_v2

    profile = load_user_profile(profile_path)
    fetch = fetcher or _fetch_text_default
    today = utc8_today()
    cache_root_path = Path(cache_root)
    stats = BaiduCacheStats()

    def live_board(_date: str) -> dict:
        return {"response_text": fetch(NETEASE_HOT_URL, 20)}

    board_payload, board_src = _news_cache_get(
        get_or_fetch_netease_news_board_with_record,
        cache_root_path, today, live_board,
        offline=offline, force_refresh=force_board_refresh,
    )
    stats.record("board", board_src, forced=force_board_refresh)
    board_text = str(board_payload.get("response_text", "")) if isinstance(board_payload, dict) else ""
    try:
        raw_board_items = parse_netease_hot_response(
            board_text, fetched_at=fetched_at) if board_text.strip() else []
    except ValueError:
        raw_board_items = []
    board_items = [
        replace(item, raw_payload={**item.raw_payload, "source_kind": "hot_board"})
        for item in raw_board_items
    ]

    if custom_keywords:
        keywords = tuple(k.strip() for k in custom_keywords if k.strip())[:5]
        source = "custom"
    else:
        keywords = tuple(w.strip() for w in profile.core_keywords if w.strip())[:5]
        source = "core_keywords"
    extraction = PersonaKeywordExtraction(
        user_id=profile.profile_id,
        persona_signature="",
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
        source=source,
    )
    persona_keywords = tuple(keywords)

    raw_search_by_keyword: dict[str, list[HotItem]] = {}
    article_info_by_key: dict[str, dict] = {}
    for word in keywords:
        def live_search(_w: str = word) -> list[dict]:
            from urllib.parse import urlencode
            url = f"{NETEASE_SEARCH_URL}?{urlencode({'query': _w})}"
            items = parse_netease_search_response(fetch(url, 20), fetched_at=fetched_at)
            return [
                {"article_id": _netease_bare_id(item.raw_payload) or item.item_id,
                 "title": item.title, "url": item.url}
                for item in items
            ]

        payload, src = _news_cache_get_search(
            get_or_fetch_netease_news_search_with_record,
            cache_root_path, today, word, live_search,
            offline=offline, force_refresh=force_search_refresh,
        )
        stats.record("search", src, forced=force_search_refresh)
        if not isinstance(payload, list):
            raw_search_by_keyword[word] = []
            continue
        items: list[HotItem] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("url", "")).strip()
            article_id = str(entry.get("article_id", "")).strip()
            if not title or not url or not article_id:
                continue
            item = HotItem(
                item_id=f"netease_news_{article_id}", platform="netease_news",
                item_type="news", title=title, url=url, rank=None,
                heat=HeatMetrics(value=None, label="", metric_name="search_rank", metrics={}),
                summary=title, category="", matched_query_ids=matched_query_ids,
                fetched_at=fetched_at, fetch_status="success",
                raw_payload={"source_kind": "netease_news_search_recall",
                             "article_id": article_id},
            )
            items.append(item)
            article_info_by_key[_netease_news_dedup_key(item)] = {
                "article_heat": 0,
                "is_toutiao_hot": False,
            }
        raw_search_by_keyword[word] = items

    ctx = NewsPathContext(
        identity_key=_netease_news_dedup_key,
        enrich_with_article_info=lambda item, _info: item,
        score_item=_netease_score_item,
    )
    candidates = build_news_candidates(
        hot_board=list(board_items),
        keywords=extraction.keywords,
        persona_keywords=persona_keywords,
        search_results_by_keyword=raw_search_by_keyword,
        article_info_by_key=article_info_by_key,
        filters=path_filters,
        ctx=ctx,
    )
    candidates = select_search_candidates_by_heat(candidates)
    candidates.sort(key=lambda candidate: as_sort_key(
        hybrid_score_v2(candidate.item, persona_keywords)))
    kept_candidates = candidates[: max(0, top_n)]

    item_details = _fetch_news_article_details(
        kept_candidates=kept_candidates,
        cache_root_path=cache_root_path,
        date=today,
        offline=offline,
        force_article_refresh=force_article_refresh,
        stats=stats,
        fetcher=fetch,
        dedup_key_fn=_netease_news_dedup_key,
        platform="netease_news",
        parser=parse_netease_article_response,
        extraction_method="netease_news_article_page",
        article_getter=get_or_fetch_netease_news_article_with_record,
    )

    report_md = render_netease_news_report_v2(
        profile, extraction, kept_candidates, fetched_at,
        item_details=item_details, cache_stats=stats,
    )
    run_result = write_news_run(
        user_id=profile.profile_id,
        date=today,
        candidates=candidates,
        top_n=top_n,
        raw_search_by_keyword=raw_search_by_keyword,
        raw_article_info_by_key=article_info_by_key,
        item_details=item_details,
        report_markdown=report_md,
        ctx=NewsOutputContext(
            canonical_url=_canonical_url,
            write_article_text=_write_news_article_text,
            fetched_at=fetched_at,
        ),
        output_root=output_root,
    )

    if on_search_committed is not None and raw_search_by_keyword:
        on_search_committed()

    return NeteaseNewsV2Result(
        user_id=profile.profile_id,
        date=today,
        run_dir=run_result.run_dir,
        top_n=top_n,
        candidates_total=run_result.candidates_total,
        kept_total=run_result.kept_total,
        paths=run_result.paths,
        hot_board_source=board_src,
        keyword_source=extraction.source,
        keyword_count=len(extraction.keywords),
        report_path=run_result.run_dir / "report.md",
        focused_path=run_result.run_dir / "focused.json",
    )


# ---------------------------------------------------------------------------
# News cache access helpers
# ---------------------------------------------------------------------------
#
# The news pipelines have no yesterday-fallback and no persistent daily board,
# so ``offline=True`` on an empty cache would strand the run with nothing to
# report. Mirror ``run_toutiao_pipeline_v2``'s smart-offline rule: when the
# platform cache is missing, offline upgrades to a live fetch (still through
# the injected fetcher, so tests stay deterministic and no real network is hit
# unless the CLI wires a live fetcher). A ``force_refresh`` request always
# skips the cache. Otherwise a cached payload is served without refetching.


def _sina_bare_id(row: dict) -> str:
    """Extract the bare Sina article id from a board/search row.

    Hot-list rows expose ``ext4`` (already bare). Search rows expose
    ``dataid`` which carries a channel prefix like ``comos:`` or
    ``k:``. The bare id is the part after the last ``:``; when the
    delimiter is absent we treat the whole string as bare. Returns ""
    when no usable id is found.
    """
    for field in ("ext4", "dataid"):
        raw = str(row.get(field) or "").strip()
        if not raw:
            continue
        if ":" in raw:
            bare = raw.rsplit(":", 1)[-1].strip()
            if bare:
                return bare
        else:
            return raw
    return ""


def _netease_bare_id(row: dict) -> str:
    """Extract the bare NetEase docid from a board/search row.

    Both ``contentId`` (board) and ``docid`` (search) already carry the
    bare id; pick whichever is present.
    """
    for field in ("contentId", "docid"):
        raw = str(row.get(field) or "").strip()
        if raw:
            return raw
    return ""


def _sina_news_dedup_key(item: HotItem) -> str:
    """Stable identity key for dedup of Sina Path A / Path B items.

    Prefers ``raw_payload['article_id']`` (set by the live search path).
    Falls back to extracting the bare id from ``ext4`` / ``dataid`` for
    board-only items whose parser leaves the raw row untouched.
    """
    raw_payload = item.raw_payload or {}
    explicit = str(raw_payload.get("article_id") or "").strip()
    if explicit:
        return explicit
    bare = _sina_bare_id(raw_payload)
    if bare:
        return bare
    return f"url:{_canonical_url(item.url)}"


def _netease_news_dedup_key(item: HotItem) -> str:
    """Stable identity key for dedup of NetEase Path A / Path B items."""
    raw_payload = item.raw_payload or {}
    explicit = str(raw_payload.get("article_id") or "").strip()
    if explicit:
        return explicit
    bare = _netease_bare_id(raw_payload)
    if bare:
        return bare
    return f"url:{_canonical_url(item.url)}"


def _news_cache_get(getter, cache_root, date, live, *, offline, force_refresh):
    if force_refresh:
        return getter(cache_root, date, live, force_refresh=True)
    return getter(cache_root, date, live)


def _news_cache_get_search(getter, cache_root, date, word, live, *, offline, force_refresh):
    if force_refresh:
        return getter(cache_root, date, word, live, force_refresh=True)
    return getter(cache_root, date, word, live)


def _news_cache_get_article(getter, cache_root, date, article_id, live, *, offline, force_refresh):
    if force_refresh:
        return getter(cache_root, date, article_id, live, force_refresh=True)
    return getter(cache_root, date, article_id, live)
