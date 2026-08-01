"""Tests for recommender orchestration (v2 UserSpec)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
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
        patch.object(recommender, "fetch_candidates", return_value=[]),
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
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
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
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
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
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
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


def test_fetch_candidates_prefer_search_drops_irrelevant_hot_when_search_yields_plenty() -> None:
    """When search produces many items (>= target_limit * 4), prefer_search
    drops ALL hot items regardless of relevance.
    """
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
    assert all("hot.com" not in u for u in urls), urls
    assert all(a.get("search_query") for a in articles)
    # 2 tracks x 5 (capped by search_results_per_interest) = 10 search
    # < plenty (20), so the "enough" branch runs. None of the hot items
    # mention either "AI" or "副业", so relevant_hot = [] and only the 10
    # search items remain.
    assert len(articles) == 10


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
    # 1 search + 2 relevant_hot + ≥1 other_hot
    assert len(search_urls) == 1
    assert len(relevant_hot_urls) == 2
    assert len(other_hot_urls) >= 1
    assert urls[0].endswith("/search.com/1")


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

    def fake_fetch(s, *, keywords=None, **kwargs):
        captured["v3_keywords"] = keywords
        return [_mock_article()]

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "extract_or_load", fake_extract),
        patch.object(recommender, "fetch_candidates", fake_fetch),
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

    def fake_fetch(s, *, keywords=None, **kwargs):
        captured["v3_keywords"] = keywords
        return [_mock_article()]

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "extract_or_load", fake_extract),
        patch.object(recommender, "fetch_candidates", fake_fetch),
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

