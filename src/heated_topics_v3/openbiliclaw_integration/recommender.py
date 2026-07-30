"""Per-user recommendation orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from heated_topics_v3.clock import SHANGHAI
from heated_topics_v3.contracts import HotItem, ItemDetail
from heated_topics_v3.openbiliclaw_integration import (
    candidate_adapter,
    output,
    runtime,
    user_profile,
)

logger = logging.getLogger(__name__)


# Re-export for convenience so tests can patch via `recommender.load_users`.
load_users = user_profile.load_users


# Default provider list (ordered by typical relevance for V3 hot topics).
# ``dailyhot:<route>`` syntax dispatches to DailyHotApiProvider — e.g.
# ``dailyhot:36kr`` for 36氪, ``dailyhot:sspai`` for 少数派. Hot-list data
# comes from data/cache/dailyhot/*.json (written by the upstream dailyhot
# client); article bodies are fetched per-URL via GNE.
_DEFAULT_PROVIDERS: tuple[str, ...] = (
    "juejin",
    "toutiao",
    "baidu_hot",
    "zhihu_hot",
    "zhihu_daily",
    "sina_news",
    "thepaper",
    "netease_news",
)


# Detail fetch cap per platform: collecting full bodies for 50 items is too
# slow and blocks the hot list. We only need bodies for the candidates the
# engine actually considers.
_DETAIL_FETCH_CAP = 20


def _build_provider(platform: str) -> Any | None:
    """Instantiate the V3 provider class for ``platform``.

    Returns None if the platform name is unknown so the caller can skip it.
    """
    import httpx as _httpx

    client = _httpx.Client(
        follow_redirects=True,
        timeout=_httpx.Timeout(20.0),
        headers={"User-Agent": "heatedtopics-v3/0.1 (+anonymous-public-data)"},
    )
    if platform.startswith("dailyhot:"):
        from heated_topics_v3.providers.dailyhot import DailyHotApiProvider

        route = platform.split(":", 1)[1]
        return DailyHotApiProvider(route, client=client), client
    if platform == "juejin":
        from heated_topics_v3.providers.juejin import JuejinProvider

        return JuejinProvider(client), client
    if platform == "toutiao":
        from heated_topics_v3.providers.toutiao import ToutiaoProvider

        return ToutiaoProvider(client), client
    if platform == "baidu_hot":
        from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

        return BaiduHotProvider(client), client
    if platform == "zhihu_hot":
        from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

        return ZhihuHotProvider(client, ""), client
    if platform == "zhihu_daily":
        from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

        return ZhihuDailyProvider(client), client
    if platform == "sina_news":
        from heated_topics_v3.providers.sina_news import SinaNewsProvider

        return SinaNewsProvider(client), client
    if platform == "thepaper":
        from heated_topics_v3.providers.thepaper import ThePaperProvider

        return ThePaperProvider(client), client
    if platform == "netease_news":
        from heated_topics_v3.providers.netease_news import NeteaseNewsProvider

        return NeteaseNewsProvider(client), client
    try:
        client.close()
    except Exception:
        pass
    return None


def _hotitem_to_article(
    item: HotItem, detail: ItemDetail | None, platform: str
) -> dict[str, Any] | None:
    """Convert a V3 HotItem (+ optional ItemDetail) into the dict shape
    that ``candidate_adapter.to_discovered`` expects.
    """
    if not item.item_id or not item.title or not item.url:
        return None
    body_text = ""
    if detail is not None and detail.content_status == "full_text" and detail.content:
        body_text = detail.content
    elif item.summary:
        body_text = item.summary
    heat_dict: dict[str, Any] = {}
    if item.heat.value is not None:
        # Map the native metric to a "view"-like key for adapter visibility.
        heat_dict["view"] = int(item.heat.value)
    if item.heat.metrics:
        for k, v in item.heat.metrics.items():
            heat_dict.setdefault(k, int(v))
    heat_dict["rank"] = item.rank or 0
    return {
        "article_id": item.item_id,
        "title": item.title,
        "url": item.url,
        "body_text": body_text,
        "summary": item.summary or "",
        "author": "",
        "published_at": item.publication_time or "",
        "tags": [],
        "heat": heat_dict,
        "platform": platform,
    }


def fetch_candidates(
    spec: user_profile.UserSpec,
    *,
    providers: list[str] | None = None,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch hot articles for one user from V3 providers.

    Each provider returns a list of Article dicts. We normalize to a flat
    list with a ``platform`` field set per article.

    Failures in individual providers are isolated: a single provider going
    down returns zero items rather than crashing the whole fetch. This is
    what tests mock.
    """
    enabled = list(providers) if providers else list(_DEFAULT_PROVIDERS)
    collected_at = datetime.now(SHANGHAI).isoformat()
    out: list[dict[str, Any]] = []
    for platform in enabled:
        built = _build_provider(platform)
        if built is None:
            logger.warning("fetch_candidates: unknown platform '%s'", platform)
            continue
        provider, client = built
        try:
            try:
                capture = provider.collect_hot_list(collected_at)
                items: tuple[HotItem, ...] = capture.items
            except Exception as exc:
                logger.warning("provider %s.collect_hot_list failed: %s", platform, exc)
                continue
            # Fetch bodies (slow). Cap to top items; the rest stay bodyless
            # (they will be skipped by the candidate adapter).
            cap_items = items[:_DETAIL_FETCH_CAP]
            for item in cap_items:
                try:
                    detail = provider.fetch_detail(item, collected_at)
                except Exception as exc:
                    logger.debug(
                        "provider %s.fetch_detail(%s) failed: %s",
                        platform,
                        item.item_id,
                        exc,
                    )
                    detail = None
                article = _hotitem_to_article(item, detail, platform)
                if article is not None:
                    out.append(article)
            # Remaining items without detail (best-effort).
            for item in items[_DETAIL_FETCH_CAP:]:
                article = _hotitem_to_article(item, None, platform)
                if article is not None:
                    out.append(article)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    return out


def _build_shared_runtime(
    shared_data_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Construct shared LLM and embedding services once per process."""
    from openbiliclaw.config import Config, LLMProviderConfig
    from openbiliclaw.llm.registry import build_embedding_service, build_llm_registry
    from openbiliclaw.llm.service import LLMService
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.storage.database import Database

    base_dir = shared_data_dir or Path.cwd() / ".openbiliclaw_shared"
    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "shared.db"
    database = Database(db_path)
    database.initialize()
    memory_manager = MemoryManager(base_dir, database=database)

    config = None
    if config_path is not None:
        config = runtime.load_openbiliclaw_config(config_path)
    if config is None:
        config = Config()
        config.llm.default_provider = "openai_compatible"
        config.llm.openai_compatible = LLMProviderConfig(
            api_key=os.environ["OPENBILICLAW_LLM_API_KEY"],
            model="MiniMax-M2.7",
            base_url="https://api.minimaxi.com/v1",
        )
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"
    elif not config.llm.embedding.provider.strip():
        config.llm.embedding.provider = "ollama"
        config.llm.embedding.model = "bge-m3"

    registry = build_llm_registry(config)
    llm_service = LLMService(registry=registry, memory=memory_manager)
    embedding_service = build_embedding_service(config, registry)

    return {
        "llm": llm_service,
        "embedding": embedding_service,
        "_memory_manager": memory_manager,
        "_database": database,
    }


def build_recommender(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    shared_runtime: Any | None = None,
    persist: bool = False,
) -> Any:
    """Build a per-user RecommendationEngine pointing at data_dir.

    LLM service and embedding service are shared across users
    (shared_runtime). Database, MemoryManager, and RecommendationEngine
    are per-user.
    """
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.recommendation.engine import RecommendationEngine
    from openbiliclaw.storage.database import Database

    if shared_runtime is None:
        shared_runtime = _build_shared_runtime(shared_data_dir=data_dir.parent)

    user_db_path = data_dir / "openbiliclaw.db"
    user_db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(user_db_path)
    database.initialize()

    memory_manager = MemoryManager(data_dir, database=database)

    engine = RecommendationEngine(
        llm=shared_runtime["llm"],
        database=database,
        embedding_service=shared_runtime.get("embedding"),
    )
    # Stash per-user handles so callers can close them.
    engine._ht_memory_manager = memory_manager  # type: ignore[attr-defined]
    engine._ht_database = database  # type: ignore[attr-defined]
    return engine


async def _run_one_user_async(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int,
    body_preview_chars: int,
    per_user_timeout: float,
    providers: list[str] | None,
    shared_runtime: Any | None,
) -> dict[str, Any]:
    """Async body of run_one_user."""
    articles = fetch_candidates(spec, providers=providers)
    if not articles:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="no_candidates",
            error_detail=f"Fetched 0 articles from providers={providers or 'all'}",
        )
    candidates = candidate_adapter.to_discovered(
        articles,
        platform=articles[0].get("platform", "juejin")
        if isinstance(articles[0], dict) and "platform" in articles[0]
        else "juejin",
    )
    # If articles don't carry 'platform' per-item, attribute by provider list order.
    if not any(isinstance(a, dict) and "platform" in a for a in articles):
        if providers and len(providers) == 1:
            candidates = candidate_adapter.to_discovered(
                articles, platform=providers[0]
            )
    profile = user_profile.build_onion_profile(spec)
    user_data_dir = user_profile.user_data_dir(data_dir, spec.user_id)
    engine = build_recommender(
        spec,
        data_dir=user_data_dir,
        shared_runtime=shared_runtime,
        persist=True,
    )
    try:
        async with asyncio.timeout(per_user_timeout):
            recommendations = await engine.serve_external_candidates(
                profile, candidates, limit=limit, persist=False
            )
    except TimeoutError:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="timeout",
            error_detail=f"exceeded {per_user_timeout}s",
        )
    except Exception as exc:
        logger.exception("user %s: engine failed", spec.user_id)
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="engine_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    if not recommendations:
        return output.format_user_failure(
            user_id=spec.user_id,
            error_code="no_recommendations",
            error_detail="Engine returned 0 recommendations",
        )
    rec_dicts = [
        output.format_recommendation(
            rec, rank=i + 1, body_preview_chars=body_preview_chars
        )
        for i, rec in enumerate(recommendations)
    ]
    user_summary = output.format_user_success_summary(
        user_id=spec.user_id,
        display_name=spec.display_name,
        interests_count=len(spec.interests),
        disliked_count=len(spec.disliked_topics),
        fetched=len(articles),
        after_filter=len(candidates),
        considered=len(candidates),
        embedding_degraded=False,
    )
    user_summary["recommendations"] = rec_dicts
    return user_summary


def run_one_user(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    limit: int = 5,
    body_preview_chars: int = 800,
    per_user_timeout: float = 180.0,
    providers: list[str] | None = None,
    shared_runtime: Any | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper around _run_one_user_async."""
    return asyncio.run(
        _run_one_user_async(
            spec,
            data_dir=data_dir,
            limit=limit,
            body_preview_chars=body_preview_chars,
            per_user_timeout=per_user_timeout,
            providers=providers,
            shared_runtime=shared_runtime,
        )
    )


async def run_all_users(
    *,
    users_path: Path,
    data_dir: Path,
    max_parallel: int = 5,
    limit: int = 5,
    body_preview_chars: int = 800,
    per_user_timeout: float = 180.0,
    providers: list[str] | None = None,
    shared_runtime: Any | None = None,
    config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Run recommendation for all users with bounded concurrency.

    Per-user failures are isolated: one user's exception does not affect
    the others. Each user gets a separate data_dir under data_dir/users/.
    """
    specs = load_users(users_path)
    if shared_runtime is None and config_path is not None:
        shared_runtime = _build_shared_runtime(
            shared_data_dir=data_dir,
            config_path=config_path,
        )
    sem = asyncio.Semaphore(max_parallel)

    async def _one(spec: user_profile.UserSpec) -> dict[str, Any]:
        async with sem:
            try:
                return await _run_one_user_async(
                    spec,
                    data_dir=data_dir,
                    limit=limit,
                    body_preview_chars=body_preview_chars,
                    per_user_timeout=per_user_timeout,
                    providers=providers,
                    shared_runtime=shared_runtime,
                )
            except Exception as exc:
                logger.exception("user %s unexpected error", spec.user_id)
                return output.format_user_failure(
                    user_id=spec.user_id,
                    error_code="internal",
                    error_detail=f"{type(exc).__name__}: {exc}",
                )

    return await asyncio.gather(*[_one(s) for s in specs])
