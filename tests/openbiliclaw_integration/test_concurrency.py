"""Tests for multi-user concurrent orchestration (v2 UserSpec)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from heated_topics_v3.openbiliclaw_integration import recommender
from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec


def _specs(n: int) -> list[UserSpec]:
    return [
        UserSpec(
            user_id=f"u{i}",
            display_name=f"U{i}",
            track_1="AI",
            track_2="副业",
            persona="博主",
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_run_all_users_serial_default(tmp_path: Path) -> None:
    specs = _specs(3)
    with patch.object(
        recommender,
        "_run_one_user_async",
        new_callable=AsyncMock,
        side_effect=[
            {"user_id": "u0", "recommendations": []},
            {"user_id": "u1", "recommendations": []},
            {"user_id": "u2", "recommendations": []},
        ],
    ):
        results = await recommender.run_all_users(
            specs=specs, data_dir=tmp_path, max_parallel=1,
            use_keyword_extraction=False,
        )
    assert set(results.keys()) == {"u0", "u1", "u2"}


@pytest.mark.asyncio
async def test_run_all_users_parallel_respects_cap(tmp_path: Path) -> None:
    specs = _specs(10)

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_run(spec, **kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return {"user_id": spec.user_id, "recommendations": []}

    with patch.object(
        recommender,
        "_run_one_user_async",
        new_callable=AsyncMock,
        side_effect=fake_run,
    ):
        results = await recommender.run_all_users(
            specs=specs, data_dir=tmp_path, max_parallel=3,
            use_keyword_extraction=False,
        )
    assert len(results) == 10
    assert max_active <= 3
    assert max_active >= 2  # actually parallel


@pytest.mark.asyncio
async def test_run_all_users_isolates_failures(tmp_path: Path) -> None:
    specs = _specs(3)

    async def fake_run(spec, **kwargs):
        if spec.user_id == "u1":
            return {"user_id": "u1", "error": "boom"}
        return {"user_id": spec.user_id, "recommendations": []}

    with patch.object(
        recommender,
        "_run_one_user_async",
        new_callable=AsyncMock,
        side_effect=fake_run,
    ):
        results = await recommender.run_all_users(
            specs=specs, data_dir=tmp_path, max_parallel=2,
            use_keyword_extraction=False,
        )
    assert len(results) == 3
    assert results["u1"]["error"] == "boom"
    assert sum(1 for r in results.values() if "error" not in r) == 2


@pytest.mark.asyncio
async def test_run_all_users_passes_raw_data_dir_no_double_nest(
    tmp_path: Path,
) -> None:
    """Regression: ``_run_one_user_async`` must receive the raw data_dir, not
    a per-user subpath. Per-user isolation is its job, not the orchestrator's.
    Otherwise we get ``data_dir/users/<id>/users/<id>/...``.
    """
    specs = _specs(2)

    captured: list[Path] = []

    async def fake_run(spec, **kwargs):
        captured.append(kwargs["data_dir"])
        return {"user_id": spec.user_id, "recommendations": []}

    with patch.object(
        recommender,
        "_run_one_user_async",
        new_callable=AsyncMock,
        side_effect=fake_run,
    ):
        await recommender.run_all_users(
            specs=specs, data_dir=tmp_path, max_parallel=2,
            use_keyword_extraction=False,
        )

    assert len(captured) == 2
    for d in captured:
        assert d == tmp_path, f"expected raw data_dir {tmp_path}, got {d}"


# --- v2.1.6: per-user intra-pipeline parallelism ----------------------------


@pytest.mark.asyncio
async def test_fetch_v3_candidates_runs_providers_in_parallel() -> None:
    """The async fetch must gather all providers concurrently — wall time
    bounded by the slowest provider, not the sum."""
    from heated_topics_v3.openbiliclaw_integration.recommender import (
        _fetch_v3_candidates_async,
    )
    from heated_topics_v3.openbiliclaw_integration import user_profile

    spec = user_profile.UserSpec(
        user_id="u_p",
        display_name="U_p",
        track_1="AI", track_2="副业", persona="博主",
    )

    # Each "provider" sleeps for the given delay before returning one article.
    n_providers = 6
    per_provider_delay = 0.3  # seconds
    # Sequential total would be n_providers * delay = 1.8s.
    # Parallel total should be ~delay (plus scheduling overhead).
    parallel_budget = per_provider_delay + 0.5  # generous budget

    def slow_hot_list(platform: str, collected_at: str, **kwargs):
        import time as _t
        _t.sleep(per_provider_delay)
        from heated_topics_v3.contracts import HeatMetrics, HotItem
        return [
            {
                "article_id": f"{platform}-1",
                "title": f"from {platform}",
                "url": f"https://{platform}.com/1",
                "body_text": "body",
                "summary": "",
                "author": "",
                "published_at": "",
                "tags": [],
                "heat": {"rank": 1, "view": 100},
                "platform": platform,
            }
        ]

    started = asyncio.get_event_loop().time()
    with patch.object(
        recommender,
        "_fetch_provider_hot_list_sync",
        side_effect=slow_hot_list,
    ):
        articles = await _fetch_v3_candidates_async(
            spec,
            providers=[f"p{i}" for i in range(n_providers)],
            use_search=False,
        )
    elapsed = asyncio.get_event_loop().time() - started

    assert len(articles) == n_providers
    # If providers ran sequentially, elapsed would be ~1.8s. Parallel should
    # be < parallel_budget. Allow some slack for CI scheduler noise.
    assert elapsed < parallel_budget, (
        f"providers ran sequentially: elapsed={elapsed:.2f}s "
        f"(budget={parallel_budget:.2f}s); n_providers={n_providers}"
    )


@pytest.mark.asyncio
async def test_fetch_last30days_runs_queries_in_parallel() -> None:
    """All resolved last30days queries run concurrently via asyncio.gather."""
    from heated_topics_v3.openbiliclaw_integration.recommender import (
        _fetch_last30days_candidates_async,
    )
    from heated_topics_v3.openbiliclaw_integration import user_profile

    spec = user_profile.UserSpec(
        user_id="u_q",
        display_name="U_q",
        track_1="x", track_2="y", persona="",
    )
    cfg = {
        "cli_path": Path("/fake"),
        "queries": ["q1", "q2", "q3"],
        "days": 30, "platforms": (), "timeout": 30.0,
        "save_dir": Path("/tmp"),
    }

    n_queries = 3
    per_query_delay = 0.3  # seconds
    parallel_budget = per_query_delay + 0.5

    def slow_one_query(spec, cfg, query, base_save_dir):
        import time as _t
        _t.sleep(per_query_delay)
        return (query, [])

    started = asyncio.get_event_loop().time()
    with patch.object(
        recommender,
        "_fetch_one_last30days_query_sync",
        side_effect=slow_one_query,
    ):
        articles = await _fetch_last30days_candidates_async(
            spec, cfg, max_queries=3,
        )
    elapsed = asyncio.get_event_loop().time() - started

    assert articles == []
    assert elapsed < parallel_budget, (
        f"queries ran sequentially: elapsed={elapsed:.2f}s "
        f"(budget={parallel_budget:.2f}s); n_queries={n_queries}"
    )
