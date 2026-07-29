"""Per-user recommendation orchestration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from heated_topics_v3.openbiliclaw_integration import candidate_adapter, output, user_profile

logger = logging.getLogger(__name__)


# Re-export for convenience so tests can patch via `recommender.load_users`.
load_users = user_profile.load_users


# Stubs -- real implementation in Task 6.2.
def fetch_candidates(
    spec: user_profile.UserSpec,
    *,
    providers: list[str] | None = None,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch articles for one user from the configured V3 providers.

    Real implementation invokes V3 provider modules. For tests, this is
    mocked.
    """
    return []


def build_recommender(
    spec: user_profile.UserSpec,
    *,
    data_dir: Path,
    shared_runtime: Any | None = None,
    persist: bool = False,
) -> Any:
    """Build (or fetch) a per-user RecommendationEngine.

    Real implementation wires LLM / embedding / database. For tests, this
    is mocked.
    """
    raise NotImplementedError("build_recommender must be patched in tests")


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
    candidates = candidate_adapter.to_discovered(articles, platform=articles[0].get("platform", "juejin") if isinstance(articles[0], dict) and "platform" in articles[0] else "juejin")
    # If articles don't carry 'platform' per-item, attribute by provider list order.
    if not any(isinstance(a, dict) and "platform" in a for a in articles):
        if providers and len(providers) == 1:
            candidates = candidate_adapter.to_discovered(articles, platform=providers[0])
    profile = user_profile.build_onion_profile(spec)
    engine = build_recommender(
        spec,
        data_dir=data_dir / spec.user_id,
        shared_runtime=shared_runtime,
        persist=True,
    )
    try:
        async with asyncio.timeout(per_user_timeout):
            recommendations = await engine.serve_external_candidates(
                profile, candidates, limit=limit
            )
    except TimeoutError:
        return output.format_user_failure(
            user_id=spec.user_id, error_code="timeout",
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
        output.format_recommendation(rec, rank=i + 1, body_preview_chars=body_preview_chars)
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
    per_user_timeout: float = 60.0,
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
