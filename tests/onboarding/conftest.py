"""Shared fixtures for onboarding tests.

The how-to tests invoke the CLI end-to-end. Without mocks, every run
would:

* Hit the V3 hot-list providers (8 HTTP requests per user, ~3s).
* Hit the LLM-backed keyword extractor (30s timeout before fallback).
* Hit the LLM-backed summary generator (20s timeout before fallback).

That makes a 1-user demo take 50+ seconds and a 2-user demo 100+ —
unfriendly for an agent just trying to verify the project runs.

This conftest auto-stubs those three call sites so the suite finishes
in a few seconds. Each test can override the candidate stub by
entering its own ``patch.object`` block; the inner-most mock wins.

The sanity tests don't run the pipeline, so this fixture is irrelevant
to them.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _stub_external_io_for_onboarding() -> Iterator[None]:
    """Stub the three slow external I/O calls in the recommender pipeline.

    * ``recommender._fetch_candidates_for_user_async`` — bypasses both V3
      hot-list providers and the last30days subprocess.
    * ``recommender.extract_or_load`` — keyword extraction returns the
      spec's tracks verbatim so query propagation still demonstrates
      real behavior.
    * ``per_query_summary.summarize_overall`` — Chinese brief generation
      returns a fixed string so ``summary.txt`` is non-empty.
    """
    from heated_topics_v3.openbiliclaw_integration import recommender

    async def _fake_candidates(*_args, **_kwargs):
        return [
            {
                "article_id": "stub-1",
                "title": "示例文章",
                "url": "https://example.com/1",
                "body_text": "stub body — 长于十个字符",
                "author": "stub",
                "heat": {"rank": 1},
                "tags": [],
                "platform": "juejin",
                # ``search_query`` is what the recommender reads to group
                # articles before generating the user-level brief; without
                # it the summary path is skipped and summary.txt is empty.
                "search_query": "stub-query",
            },
        ]

    def _fake_extract(spec, llm, cache_dir, *, n=3, timeout=30.0):
        return [spec.track_1, spec.track_2, spec.persona][:n]

    async def _fake_summary(**_kwargs):
        return "（onboarding 测试桩）— LLM 摘要被 stubbed。"

    summary_target = (
        "heated_topics_v3.openbiliclaw_integration.per_query_summary"
        ".summarize_overall"
    )
    with (
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            new=_fake_candidates,
        ),
        patch.object(recommender, "extract_or_load", side_effect=_fake_extract),
        patch(summary_target, side_effect=_fake_summary),
    ):
        yield


@pytest.fixture
def onboarding_article_stub() -> dict:
    """A canonical candidate dict tests can assert against."""
    return {
        "article_id": "stub-1",
        "title": "示例文章",
        "url": "https://example.com/1",
        "body_text": "stub body — 长于十个字符",
        "author": "stub",
        "heat": {"rank": 1},
        "tags": [],
        "platform": "juejin",
    }