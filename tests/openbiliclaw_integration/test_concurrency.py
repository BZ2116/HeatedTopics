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
            specs=specs, data_dir=tmp_path, max_parallel=1
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
            specs=specs, data_dir=tmp_path, max_parallel=3
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
            specs=specs, data_dir=tmp_path, max_parallel=2
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
            specs=specs, data_dir=tmp_path, max_parallel=2
        )

    assert len(captured) == 2
    for d in captured:
        assert d == tmp_path, f"expected raw data_dir {tmp_path}, got {d}"
