"""Verify the OpenBiliClaw patch is present and callable."""

from __future__ import annotations

import asyncio


def test_serve_external_candidates_method_present() -> None:
    from openbiliclaw.recommendation.engine import RecommendationEngine

    assert hasattr(RecommendationEngine, "serve_external_candidates")
    assert asyncio.iscoroutinefunction(RecommendationEngine.serve_external_candidates)


def test_runtime_verify_patch_does_not_raise() -> None:
    from heated_topics_v3.openbiliclaw_integration import runtime

    runtime.verify_patch()
