"""Tests for multi-user concurrent orchestration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from heated_topics_v3.openbiliclaw_integration import recommender


def _users(n: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "users": [
            {
                "user_id": f"u{i}",
                "display_name": f"U{i}",
                "interests": [{"name": "x", "category": "x", "weight": 0.5}],
            }
            for i in range(n)
        ]
    }


@pytest.mark.asyncio
async def test_run_all_users_serial_default(tmp_path: Path) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(_users(3), ensure_ascii=False), encoding="utf-8")
    with patch.object(
        recommender, "_run_one_user_async",
        new_callable=AsyncMock,
        side_effect=[
            {"user_id": "u0", "recommendations": []},
            {"user_id": "u1", "recommendations": []},
            {"user_id": "u2", "recommendations": []},
        ],
    ):
        results = await recommender.run_all_users(
            users_path=users_p, data_dir=tmp_path, max_parallel=1
        )
    assert len(results) == 3
    assert [r["user_id"] for r in results] == ["u0", "u1", "u2"]


@pytest.mark.asyncio
async def test_run_all_users_parallel_respects_cap(tmp_path: Path) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(_users(10), ensure_ascii=False), encoding="utf-8")

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
        recommender, "_run_one_user_async",
        new_callable=AsyncMock, side_effect=fake_run,
    ):
        results = await recommender.run_all_users(
            users_path=users_p, data_dir=tmp_path, max_parallel=3
        )
    assert len(results) == 10
    assert max_active <= 3
    assert max_active >= 2  # actually parallel


@pytest.mark.asyncio
async def test_run_all_users_isolates_failures(tmp_path: Path) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(json.dumps(_users(3), ensure_ascii=False), encoding="utf-8")

    async def fake_run(spec, **kwargs):
        if spec.user_id == "u1":
            return {"user_id": "u1", "error": "boom"}
        return {"user_id": spec.user_id, "recommendations": []}

    with patch.object(
        recommender, "_run_one_user_async",
        new_callable=AsyncMock, side_effect=fake_run,
    ):
        results = await recommender.run_all_users(
            users_path=users_p, data_dir=tmp_path, max_parallel=2
        )
    assert len(results) == 3
    assert any(r.get("error") == "boom" for r in results)
    assert sum(1 for r in results if "error" not in r) == 2