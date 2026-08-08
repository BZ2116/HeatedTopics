"""Tests for recommender orchestration (v2 UserSpec)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.contracts import ItemDetail
from heated_topics_v3.openbiliclaw_integration import recommender
from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec


def _mock_article(
    article_id: str = "1", title: str = "T", platform: str = "juejin"
) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": title,
        "url": f"https://{platform}.com/{article_id}",
        "body_text": "body",
        "author": "a",
        "heat": {"view": 100, "like": 10, "comment": 1, "rank": 1},
        "tags": [],
    }


def _mock_recommendation(
    title: str = "T", source_rank: int = 1
) -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id="1",
        content_url="https://x.com/1",
        source_platform="juejin",
        body_text="body",
        content_type="note",
        source_rank=source_rank,
    )
    return Recommendation(
        content=item,
        expression="ignored",
        topic_label="ignored",
        confidence=0.8,
        presented=False,
    )


def _make_spec(
    user_id: str = "u1",
    track_1: str = "AI",
    track_2: str = "副业",
) -> UserSpec:
    return UserSpec(
        user_id=user_id, display_name=user_id,
        track_1=track_1, track_2=track_2, persona="博主",
    )


def test_run_one_user_returns_recommendations(tmp_path: Path) -> None:
    spec = _make_spec()
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[_mock_article(title="鍙ゅ吀鏂囧鐩稿叧")]),
        ),
    ):
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=False,
        )
    assert result["user_id"] == spec.user_id
    assert "recommendations" in result
    assert len(result["recommendations"]) == 1
    # v2: no reason/topic_label/confidence in output
    rec = result["recommendations"][0]
    assert "reason" not in rec
    assert "topic_label" not in rec
    assert "confidence" not in rec


def test_run_one_user_handles_no_candidates(tmp_path: Path) -> None:
    spec = _make_spec()
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(return_value=[])

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[]),
        ),
    ):
        result = recommender.run_one_user(
            spec, data_dir=tmp_path / "runtime", limit=5,
            use_keyword_extraction=False,
        )
    assert "error" in result
    assert result["error"] == "no_candidates"


def test_run_one_user_timeout_returns_error(tmp_path: Path) -> None:
    spec = _make_spec()
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(side_effect=TimeoutError)

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[_mock_article(title="鍙ゅ吀文學相关")]),
        ),
    ):
        result = recommender.run_one_user(
            spec, data_dir=tmp_path / "runtime", limit=5, per_user_timeout=0.1,
            use_keyword_extraction=False,
        )
    assert "error" in result


def test_run_one_user_isolated_engine_per_user(tmp_path: Path) -> None:
    """Each user gets a per-user data_dir."""
    specs = [_make_spec(f"u{i}") for i in range(3)]
    engines: list[tuple[str, Path]] = []

    def fake_build_recommender(spec, data_dir, **kwargs):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[_mock_recommendation()])
        engines.append((spec.user_id, data_dir))
        return eng

    with (
        patch.object(
            recommender, "build_recommender", side_effect=fake_build_recommender
        ),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[_mock_article()]),
        ),
    ):
        for spec in specs:
            recommender.run_one_user(
                spec, data_dir=tmp_path / "runtime", limit=5,
                use_keyword_extraction=False,
            )
    assert len(engines) == 3
    # Each user gets a distinct data_dir
    assert len({d for _, d in engines}) == 3


def test_run_one_user_engine_error_returns_error(tmp_path: Path) -> None:
    """Engine-side exceptions become error envelope, not crash."""
    spec = _make_spec()
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        side_effect=RuntimeError("synthetic engine failure")
    )
    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[_mock_article()]),
        ),
    ):
        result = recommender.run_one_user(
            spec, data_dir=tmp_path / "runtime", limit=5,
            use_keyword_extraction=False,
        )
    assert result["error"] == "engine_error"
    assert "RuntimeError" in result["error_detail"]


def test_build_provider_dispatches_dailyhot_route() -> None:
    """``dailyhot:<route>`` resolves to DailyHotApiProvider(route)."""
    from heated_topics_v3.providers.dailyhot import DailyHotApiProvider

    built = recommender._build_provider("dailyhot:36kr")
    assert built is not None
    provider, client = built
    assert isinstance(provider, DailyHotApiProvider)
    assert provider.platform == "36kr"
    client.close()


def test_build_provider_returns_none_for_unknown() -> None:
    assert recommender._build_provider("totally_made_up_platform") is None


def _make_hotitem(item_id: str, url: str, title: str = "T"):
    from heated_topics_v3.contracts import HeatMetrics, HotItem

    return HotItem(
        item_id=item_id,
        platform="toutiao",
        title=title,
        url=url,
        rank=1,
        heat=HeatMetrics(value=None, label="hot", metric_name="hot_value", metrics={}),
        summary="",
        publication_time="",
        collected_at="",
    )


def _build_search_spec() -> UserSpec:
    """Spec with 2 tracks for search ordering tests."""
    return UserSpec(
        user_id="u1",
        display_name="U1",
        track_1="AI",
        track_2="副业",
        persona="博主",
    )


def test_fetch_candidates_invokes_search_on_top_k_tracks() -> None:
    """When use_search=True and tracks are set, fetch_candidates calls
    search() once per top-K track on each search-enabled provider."""
    spec = _build_search_spec()
    search_calls: list[tuple[str, str]] = []

    class FakeProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("h1", "https://hot.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            search_calls.append((self.platform, keyword))
            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem(f"s-{keyword}", f"https://s.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(FakeProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], search_top_k=2,
        )
    keywords = {kw for _, kw in search_calls}
    # Top-2 tracks: track_1="AI", track_2="副业"
    assert keywords == {"AI", "副业"}
    assert len(search_calls) == 2
    # Hot-list article + 2 search articles
    urls = [a["url"] for a in articles]
    assert len(urls) == 3
    assert len(set(urls)) == 3
    search_articles = [a for a in articles if a.get("search_query")]
    assert {a["search_query"] for a in search_articles} == {"AI", "副业"}


def test_fetch_candidates_dedups_overlap_between_hot_list_and_search() -> None:
    """Same URL in both passes → returned once (hot-list wins)."""
    spec = _build_search_spec()
    shared_url = "https://shared.com/x"

    class FakeProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("shared", shared_url),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("shared", shared_url, title="dup"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(FakeProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], search_top_k=1,
        )
    urls = [a["url"] for a in articles]
    assert urls == [shared_url]
    assert "search_query" not in articles[0]


def test_fetch_candidates_isolates_search_failure() -> None:
    """One (provider, track) pair raising must not crash the fetch."""
    spec = _build_search_spec()

    class PartialFailProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("h", "https://hot.com/h"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            if keyword == "副业":
                raise RuntimeError("synthetic search failure")
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem(f"good-{keyword}", f"https://g.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(PartialFailProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], search_top_k=2,
        )
    # Hot + 1 search = 2 articles. The '副业' keyword raise is logged & skipped.
    assert len(articles) == 2
    search_articles = [a for a in articles if a.get("search_query")]
    assert [a["search_query"] for a in search_articles] == ["AI"]


def test_fetch_candidates_use_search_false_skips_search_pass() -> None:
    """Passing use_search=False must not call provider.search at all."""
    spec = _build_search_spec()
    search_called = False

    class FakeProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("h", "https://h.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            nonlocal search_called
            search_called = True
            from heated_topics_v3.providers.common import ProviderCapture
            return ProviderCapture(raw_text="", raw_suffix="", items=(), metadata={})

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(FakeProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], use_search=False
        )
    assert not search_called
    assert len(articles) == 1
    assert "search_query" not in articles[0]


def test_fetch_candidates_skips_search_when_no_tracks() -> None:
    """When both track_1 and track_2 are empty, search pass is skipped."""
    spec = UserSpec(
        user_id="u1", display_name="U1",
        track_1="x", track_2="", persona="",
    )
    search_called = False

    class FakeProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("h", "https://h.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            nonlocal search_called
            search_called = True
            from heated_topics_v3.providers.common import ProviderCapture
            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("s", f"https://s.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(FakeProvider(), fake_client)
    ):
        # track_2 empty: only track_1 "x" → 1 search call expected
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], search_top_k=3,
        )
    assert search_called is True
    # 1 hot + 1 search = 2 unique URLs
    urls = [a["url"] for a in articles]
    assert len(urls) == 2
    assert len(set(urls)) == 2


def test_fetch_candidates_search_only_runs_on_enabled_providers() -> None:
    """Search only runs on providers in the user's enabled list."""
    spec = _build_search_spec()
    toutiao_called = {"search": 0}

    class ToutiaoOnly:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("h", "https://t.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            toutiao_called["search"] += 1
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem(f"s-{keyword}", f"https://t.com/s/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(ToutiaoOnly(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], search_top_k=2,
        )
    assert toutiao_called["search"] == 2
    # 1 hot + 2 search = 3 articles.
    assert len(articles) == 3


def test_is_hot_relevant_keyword_match() -> None:
    tracks = ["非遗"]
    relevant = {
        "title": "苏绣：非遗手工的当代叙事",
        "body_text": "讲讲非遗手艺的年轻人",
        "summary": "",
    }
    irrelevant = {
        "title": "解放军两次警告日方不能自称海军",
        "body_text": "海上对峙的最新进展",
        "summary": "",
    }
    assert recommender._is_hot_relevant(relevant, tracks) is True
    assert recommender._is_hot_relevant(irrelevant, tracks) is False
    assert recommender._is_hot_relevant(
        {"title": "", "body_text": "", "summary": ""}, tracks
    ) is False
    assert (
        recommender._is_hot_relevant(
            {"title": "x", "body_text": "y", "summary": ""}, []
        )
        is False
    )


def test_fetch_candidates_keeps_hot_before_search_backfill() -> None:
    """Search supplements the hot list instead of replacing it."""
    spec = _build_search_spec()

    class ManySearchProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(
                    _make_hotitem("h1", "https://hot.com/h1", title="军事新闻"),
                    _make_hotitem("h2", "https://hot.com/h2", title="南海局势"),
                    _make_hotitem("h3", "https://hot.com/h3", title="台风快讯"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "zzz", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=tuple(
                    _make_hotitem(
                        f"{keyword}-{i}",
                        f"https://search.com/{keyword}/{i}",
                        title=f"zzz{i}",
                    )
                    for i in range(50)
                ),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(ManySearchProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"],
            search_top_k=2, target_limit=5, prefer_search=True,
        )
    urls = [a["url"] for a in articles]
    assert urls[:3] == [
        "https://hot.com/h1", "https://hot.com/h2", "https://hot.com/h3",
    ]
    assert any(a.get("search_query") for a in articles[3:])


def test_fetch_candidates_prefer_search_backfills_when_search_is_thin() -> None:
    """When search is thin (< target_limit), backfill with relevant hot
    items first; tail-fill with other_hot to reach the engine's pool size."""
    spec = UserSpec(
        user_id="u1", display_name="U1",
        track_1="非遗", track_2="", persona="",
    )

    class ThinSearchProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(
                    _make_hotitem("h_relevant_1", "https://r.com/1", title="非遗手工"),
                    _make_hotitem("h_relevant_2", "https://r.com/2", title="老手艺传承"),
                    _make_hotitem("h_other_1", "https://o.com/1", title="军事新闻"),
                    _make_hotitem("h_other_2", "https://o.com/2", title="南海局势"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem("s1", "https://search.com/1", title=f"{keyword}第1篇"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(ThinSearchProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"],
            search_top_k=1, target_limit=5, prefer_search=True,
        )
    urls = [a["url"] for a in articles]
    search_urls = [u for u in urls if "search.com" in u]
    relevant_hot_urls = [u for u in urls if "r.com" in u]
    other_hot_urls = [u for u in urls if "o.com" in u]
    # Hot list is first; search is appended only to supplement it.
    assert len(search_urls) == 1
    assert len(relevant_hot_urls) == 2
    assert len(other_hot_urls) >= 1
    assert urls[0].endswith("/r.com/1")


def test_fetch_candidates_no_prefer_search_keeps_all_hot() -> None:
    """With prefer_search=False, V3 merge: all hot + all search, dedup'd."""
    spec = _build_search_spec()

    class AllProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(
                    _make_hotitem("h1", "https://hot.com/h1", title="军事新闻"),
                    _make_hotitem("h2", "https://hot.com/h2", title="南海局势"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "body", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="", raw_suffix="",
                items=(_make_hotitem(f"s-{keyword}", f"https://s.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender, "_build_provider", return_value=(AllProvider(), fake_client)
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"],
            search_top_k=2, prefer_search=False,
        )
    # 2 hot + 2 search = 4 (all).
    assert len(articles) == 4
    hot_urls = [a["url"] for a in articles if "hot.com" in a["url"]]
    assert len(hot_urls) == 2


def test_run_one_user_extracts_keywords_when_enabled(tmp_path: Path) -> None:
    """When keyword extraction is enabled, LLM keywords flow into V3
    search queries."""
    spec = _make_spec(track_1="非遗", track_2="民俗")
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )
    captured: dict[str, Any] = {}
    fake_runtime = {"llm": MagicMock()}

    async def fake_extract(s, llm, cache_dir, *, n=3):
        captured["extracted_user"] = s.user_id
        return ["非遗手工艺", "传统节气", "老字号"]

    async def fake_fetch(s, *, keywords=None, **kwargs):
        captured["v3_keywords"] = keywords
        return [_mock_article()]

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "extract_or_load", fake_extract),
        patch.object(recommender, "_fetch_candidates_for_user_async", fake_fetch),
    ):
        recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=True,
            keyword_cache_dir=tmp_path / "_kw_cache",
            shared_runtime=fake_runtime,
        )
    assert captured["extracted_user"] == spec.user_id
    assert captured["v3_keywords"] == ["非遗手工艺", "传统节气", "老字号"]


def test_run_one_user_skips_extraction_when_disabled(tmp_path: Path) -> None:
    """When --no-keyword-extraction is set, LLM is not called; tracks
    fall back to track_1/track_2."""
    spec = _make_spec()
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )
    called = {"extract": False}
    captured: dict[str, Any] = {}
    fake_runtime = {"llm": MagicMock()}

    async def fake_extract(s, llm, cache_dir, *, n=3):
        called["extract"] = True
        return ["x", "y", "z"]

    async def fake_fetch(s, *, keywords=None, **kwargs):
        captured["v3_keywords"] = keywords
        return [_mock_article()]

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "extract_or_load", fake_extract),
        patch.object(recommender, "_fetch_candidates_for_user_async", fake_fetch),
    ):
        recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=False,
            shared_runtime=fake_runtime,
        )
    assert called["extract"] is False
    assert captured["v3_keywords"] is None  # signals "fall back to tracks"


def test_run_one_user_passes_keyword_vectors_to_adapter(tmp_path: Path) -> None:
    """When keywords are extracted, embedding service + keyword vectors
    are threaded into candidate_adapter.to_discovered for relevance scoring."""
    from heated_topics_v3.openbiliclaw_integration import candidate_adapter

    spec = _make_spec(track_1="非遗", track_2="民俗")
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )
    captured: dict[str, Any] = {}
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(side_effect=[
        [1.0, 0.0, 0.0],  # keyword 1
        [0.0, 1.0, 0.0],  # keyword 2
        [0.0, 0.0, 1.0],  # keyword 3
        [0.5, 0.5, 0.0],  # article (niche fallback may invoke embed again)
        [0.5, 0.5, 0.0],  # spare
        [0.5, 0.5, 0.0],  # spare
    ])
    fake_runtime = {"llm": MagicMock(), "embedding": fake_emb}

    async def fake_extract(s, llm, cache_dir, *, n=3):
        return ["非遗", "节气", "民俗"]

    real_to_discovered = candidate_adapter.to_discovered

    async def spy_to_discovered(articles, *, platform, **kwargs):
        captured.setdefault("calls", []).append({
            "keyword_vectors": kwargs.get("keyword_vectors"),
            "sim_threshold": kwargs.get("sim_threshold"),
            "embedding_service": kwargs.get("embedding_service"),
            "platform": platform,
        })
        return await real_to_discovered(articles, platform=platform, **kwargs)

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "extract_or_load", fake_extract),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[_mock_article()]),
        ),
        patch.object(candidate_adapter, "to_discovered", spy_to_discovered),
    ):
        recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=True,
            keyword_cache_dir=tmp_path / "_kw_cache",
            shared_runtime=fake_runtime,
        )

    # At least one call to to_discovered, and it received our keyword vectors.
    assert len(captured["calls"]) >= 1
    first = captured["calls"][0]
    assert first["embedding_service"] is fake_emb
    assert first["sim_threshold"] == pytest.approx(0.5)
    assert first["keyword_vectors"] == [
        [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
    ]
    # 3 keyword embeddings + 1 article embedding (to_discovered) = 4 total.
    assert fake_emb.embed.call_count == 4


# --- v2.1.4: heat metric normalization + niche fallback ---


def test_normalize_heat_metrics_real_metrics_win_over_composite() -> None:
    """When HeatMetrics carries real view/like/comment metrics alongside a
    composite ``value``, the real metrics populate the heat dict and the
    composite is dropped — fixing the long-standing setdefault bug that
    made ``min_view_count`` filtering useless."""
    from heated_topics_v3.contracts import HeatMetrics

    heat = HeatMetrics(
        value=100,  # composite hot_rank score
        label="100",
        metric_name="hot_rank",
        metrics={"views": 5, "likes": 3, "collects": 1, "comments": 2},
    )
    out = recommender._normalize_heat_metrics(heat)
    assert out["view"] == 5        # NOT 100 (composite)
    assert out["like"] == 3
    assert out["favorite"] == 1    # collects → favorite
    assert out["comment"] == 2


def test_normalize_heat_metrics_composite_only_does_not_set_view() -> None:
    """When only a composite score is available (baidu_hot, zhihu_hot, etc.),
    the composite is left as-is and no synthetic view is invented from it —
    downstream readers won't mistake a platform hot-score for user engagement."""
    from heated_topics_v3.contracts import HeatMetrics

    heat = HeatMetrics(
        value=999, label="999", metric_name="hot_score",
        metrics={"hot_score": 999},
    )
    out = recommender._normalize_heat_metrics(heat)
    assert "view" not in out
    assert out["hot_score"] == 999


def test_normalize_heat_metrics_aliases_per_provider_names() -> None:
    """toutiao search emits 'reads' (→ view), thepaper emits 'praise_times'
    (→ like). Names that map to the same adapter key are de-duped via
    setdefault — first wins."""
    from heated_topics_v3.contracts import HeatMetrics

    heat = HeatMetrics(
        value=None, label="", metric_name="",
        metrics={
            "reads": 1234,
            "praise_times": 56,
            "comments": 7,
            "interaction_num": 200,
        },
    )
    out = recommender._normalize_heat_metrics(heat)
    assert out["view"] == 1234         # reads → view
    assert out["like"] == 56           # praise_times → like
    assert out["comment"] == 7         # comments → comment
    assert out["interaction_num"] == 200  # pass-through


def test_run_one_user_niche_persona_retries_with_zero_threshold(
    tmp_path: Path,
) -> None:
    """When the strict sim_threshold pre-filter empties the candidate pool
    (niche persona, off-keyword embeddings), the recommender retries once
    with sim_threshold=0 so any keyword-adjacent article can survive the
    final engine filter."""
    from heated_topics_v3.openbiliclaw_integration import candidate_adapter

    spec = _make_spec(track_1="古典文学", track_2="诗词鉴赏")
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation("古典文学相关")]
    )

    # Embedding service that returns a vector on every call.
    fake_emb = AsyncMock()
    fake_emb.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    # Patch to_discovered: first call returns [] (strict filter emptied
    # the pool), second call returns one candidate.
    calls: list[float] = []
    real_to_discovered = candidate_adapter.to_discovered

    async def spy(articles, *, platform, **kwargs):
        calls.append(kwargs.get("sim_threshold"))
        if len(calls) == 1:
            return []
        return [_mock_article()]

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender,
            "extract_or_load",
            AsyncMock(return_value=["古典文学", "诗词", "古文"]),
        ),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[_mock_article(title="古典文学相关")]),
        ),
        patch.object(candidate_adapter, "to_discovered", spy),
    ):
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            keyword_cache_dir=tmp_path / "_kw_cache",
            limit=5,
            use_keyword_extraction=True,
            shared_runtime={"llm": MagicMock(), "embedding": fake_emb},
        )

    assert "error" not in result, f"expected recommendations, got error: {result}"
    assert len(result["recommendations"]) == 1
    # First strict attempt (0.5), then niche retry (0.0).
    assert calls == [pytest.approx(0.5), pytest.approx(0.0)]



# --- search_query propagation + overall summary -----------------------------


def test_run_one_user_propagates_search_query_to_recommendations(tmp_path: Path) -> None:
    """When fetch articles carry ``search_query``, every recommendation whose
    ``content_id`` matches an article must expose that query string."""
    spec = _make_spec()

    article_a = _mock_article(article_id="art-A", title="title A")
    article_a["search_query"] = "夏日美食"
    article_b = _mock_article(article_id="art-B", title="title B")
    article_b["search_query"] = "面试技巧"

    rec_a = _mock_recommendation(title="title A")
    rec_a.content.content_id = "art-A"
    rec_b = _mock_recommendation(title="title B")
    rec_b.content.content_id = "art-B"
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[rec_a, rec_b]
    )

    fake_runtime = {"llm": MagicMock()}
    # LLM returns empty so the overall summary uses its deterministic fallback;
    # this test only cares about search_query propagation.
    fake_runtime["llm"].complete_with_core_memory = AsyncMock(
        return_value=MagicMock(content="")
    )

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[article_a, article_b]),
        ),
    ):
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=False,
            shared_runtime=fake_runtime,
        )

    sq_by_rank = {r["rank"]: r["search_query"] for r in result["recommendations"]}
    assert sq_by_rank[1] == "夏日美食"
    assert sq_by_rank[2] == "面试技巧"


def test_run_one_user_empty_search_query_for_hot_list_items(tmp_path: Path) -> None:
    """Hot-list items have no search_query; recommendations sourced from
    them get an empty string (preserves the field's contract)."""
    spec = _make_spec()

    article_hot = _mock_article(article_id="art-H", title="hot title")
    # No search_query field — emulates V3 hot list (no specific query).
    rec = _mock_recommendation(title="hot title")
    rec.content.content_id = "art-H"

    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(return_value=[rec])

    fake_runtime = {"llm": MagicMock()}
    fake_runtime["llm"].complete_with_core_memory = AsyncMock(
        return_value=MagicMock(content="")
    )

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[article_hot]),
        ),
    ):
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=False,
            shared_runtime=fake_runtime,
        )

    assert result["recommendations"][0]["search_query"] == ""


def test_run_one_user_includes_overall_summary_in_output(tmp_path: Path) -> None:
    """All matched query groups are summarized in one LLM call and one field."""
    spec = _make_spec()

    article_a = _mock_article(article_id="art-A", title="title A")
    article_a["search_query"] = "夏日美食"
    article_b = _mock_article(article_id="art-B", title="title B")
    article_b["search_query"] = "面试技巧"

    rec_a = _mock_recommendation(title="title A")
    rec_a.content.content_id = "art-A"
    rec_b = _mock_recommendation(title="title B")
    rec_b.content.content_id = "art-B"
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[rec_a, rec_b]
    )

    fake_runtime = {"llm": MagicMock()}
    fake_runtime["llm"].complete_with_core_memory = AsyncMock(
        return_value=MagicMock(content="美食探店与面试准备构成两个内容方向")
    )

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[article_a, article_b]),
        ),
    ):
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=False,
            shared_runtime=fake_runtime,
        )

    assert result["summary"] == "美食探店与面试准备构成两个内容方向"
    assert fake_runtime["llm"].complete_with_core_memory.call_count == 1
    prompt = fake_runtime["llm"].complete_with_core_memory.call_args.kwargs["user_input"]
    assert "夏日美食" in prompt
    assert "面试技巧" in prompt


def test_run_one_user_has_empty_summary_when_no_search_query(tmp_path: Path) -> None:
    """If no article has a search_query, no summary call is needed."""
    spec = _make_spec()

    article_hot = _mock_article(article_id="art-H", title="hot")
    rec = _mock_recommendation(title="hot")
    rec.content.content_id = "art-H"
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(return_value=[rec])

    fake_runtime = {"llm": MagicMock()}

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(
            recommender, "_fetch_candidates_for_user_async",
            AsyncMock(return_value=[article_hot]),
        ),
    ):
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
            use_keyword_extraction=False,
            shared_runtime=fake_runtime,
        )

    assert result["summary"] == ""
    assert fake_runtime["llm"].complete_with_core_memory.call_count == 0
def test_article_source_filter_keeps_xiaohongshu_text_and_drops_video() -> None:
    assert recommender._is_article_candidate(
        {"platform": "xiaohongshu", "content_type": "note", "title": "非遗手艺", "body_text": "正文"}
    )
    assert not recommender._is_article_candidate(
        {"platform": "xiaohongshu", "content_type": "video", "title": "非遗手艺", "body_text": "正文"}
    )
