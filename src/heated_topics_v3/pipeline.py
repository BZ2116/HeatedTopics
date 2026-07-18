import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from heated_topics_v3.contracts import ExtractedKeyword, ItemDetail, MatchResult, UserProfile
from heated_topics_v3.hot_board_cache import get_or_fetch_hot_board, hot_board_cache_path, utc8_today
from heated_topics_v3.llm_client import call_llm
from heated_topics_v3.llm_keywords import PersonaKeywordExtraction, extract_persona_keywords
from heated_topics_v3.matching import match_hot_item_to_queries
from heated_topics_v3.profile_loader import is_legacy_profile, load_persona_profile
from heated_topics_v3.profile_queries import build_topic_queries
from heated_topics_v3.providers.juejin import fetch_juejin_hot_items, fetch_juejin_item_detail
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
    render_article_summary_md,
    render_juejin_report,
    render_toutiao_report,
    render_toutiao_report_v2,
)
from heated_topics_v3.serialization import to_plain_data
from heated_topics_v3.toutiao_output import write_toutiao_run
from heated_topics_v3.toutiao_paths import (
    PathFilters,
    build_candidates,
    build_hot_board_candidates,
    select_search_candidates_by_heat,
)
from heated_topics_v3.toutiao_scoring import as_sort_key, hybrid_score_v2

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
        report_renderer(profile, matches, fetched_at, item_details),
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
    llm_cache_root: Path = Path("cache/llm"),
    use_llm_keywords: bool = True,
    use_llm_summary: bool = False,
    force_hot_board_refresh: bool = False,
    allow_yesterday_fallback: bool = True,
    offline: bool = False,
    top_n: int = 10,
    path_filters: PathFilters = PathFilters(),
    fetcher: Callable[[str, int], str] | None = None,
    article_info_fetcher: Callable[[str, int], str] | None = None,
    detail_fetcher: Callable[[str, int], str] | None = None,
    rendered_text_fetcher: Callable[[str, int], str] | None = None,
    llm_caller: Callable[..., str] | None = None,
    custom_keywords: tuple[str, ...] = (),
    on_search_committed: Callable[[], None] | None = None,
) -> "ToutiaoV2Result":
    """Persona-driven Toutiao pipeline.

    Steps:
      1. Load + validate v2 profile.
      2. Extract persona keywords (cache → LLM → core_keywords fallback).
      3. Read/write daily hot board cache.
      4. Per-keyword search, enrich with mobile article info.
      5. Build candidates via Paths A/B/C and rank by heat.
      6. Sort + slice top_n.
      7. Fetch item details for kept candidates.
      8. Render Markdown report (optional LLM summary section).
      9. Write per-user per-date run directory.
    """
    if is_legacy_profile(profile_path):
        raise ValueError(
            f"{profile_path} uses legacy v1 schema; please migrate to v2 "
            "(see heated_topics_v3.profile_loader.migrate_v1_to_v2)"
        )

    profile = load_persona_profile(profile_path)
    effective_llm = llm_caller or (lambda *a, **kw: call_llm(*a, cache_dir=llm_cache_root, **kw))
    if custom_keywords:
        extraction = PersonaKeywordExtraction(
            user_id=profile.user_id,
            persona_signature=profile.persona_signature,
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in custom_keywords),
            source="custom",
        )
    else:
        extraction = extract_persona_keywords(
            profile,
            cache_dir=persona_keyword_cache_root,
            use_cache=True,
            llm=effective_llm,
            allow_llm=use_llm_keywords,
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
        for keyword in keyword_phrases:
            try:
                results = fetch_toutiao_search_pages(
                    keyword,
                    fetched_at=fetched_at,
                    max_pages=path_filters.search_pages or 1,
                    per_page=path_filters.per_page,
                    fetcher=fetcher,
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

    summary_md = render_article_summary_md(
        top_candidates,
        item_details,
        llm=effective_llm if use_llm_summary else None,
    )

    report_md = render_toutiao_report_v2(
        profile,
        extraction,
        top_candidates,
        fetched_at=fetched_at,
        item_details=item_details,
        llm_summary=(effective_llm if use_llm_summary else None),
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

    if summary_md is not None:
        summary_path = run_result.run_dir / "articles" / "summary.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary_md, encoding="utf-8")

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
