"""Tests for recommender orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.recommendation.engine import Recommendation

from heated_topics_v3.contracts import ItemDetail
from heated_topics_v3.openbiliclaw_integration import recommender, user_profile


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
    title: str = "T", topic: str = "tp", reason: str = "r", confidence: float = 0.8
) -> Recommendation:
    item = DiscoveredContent(
        title=title,
        content_id="1",
        content_url="https://x.com/1",
        source_platform="juejin",
        body_text="body",
        content_type="note",
    )
    return Recommendation(
        content=item,
        expression=reason,
        topic_label=topic,
        confidence=confidence,
        presented=False,
    )


def test_run_one_user_returns_recommendations(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )

    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(
        return_value=[_mock_recommendation()]
    )

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(
            spec,
            data_dir=tmp_path / "runtime",
            limit=5,
        )
    assert result["user_id"] == spec.user_id
    assert "recommendations" in result
    assert len(result["recommendations"]) == 1
    assert result["pipeline"]["candidates_fetched"] == 1


def test_run_one_user_handles_no_candidates(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(return_value=[])

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=[]),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)
    assert "error" in result
    assert result["error"] == "no_candidates"


def test_run_one_user_timeout_returns_error(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(side_effect=TimeoutError)

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=[_mock_article()]),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(
            spec, data_dir=tmp_path / "runtime", limit=5, per_user_timeout=0.1
        )
    assert "error" in result


def test_run_one_user_isolated_engine_per_user(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    engines = []

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
        for spec in recommender.load_users(users_p):
            recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)
    assert len(engines) == 3
    # Each user gets a distinct data_dir
    assert len({d for _, d in engines}) == 3


def test_run_one_user_propagates_rank_to_confidence(
    tmp_path: Path, users_valid_3users: dict
) -> None:
    """End-to-end-ish: fetch_candidates returns articles with various ranks,
    the engine mirrors real OpenBiliClaw behavior (sets ``confidence`` from
    ``content.relevance_score``), and the output dict reflects the non-zero
    confidence. Regression for the ``confidence: 0.0`` bug where
    candidate_adapter never set relevance_score.
    """

    users_p = tmp_path / "users.json"
    users_p.write_text(
        json.dumps(users_valid_3users, ensure_ascii=False), encoding="utf-8"
    )
    articles = [
        {**_mock_article(article_id=f"a{i}"), "heat": {"rank": i}}
        for i in (1, 2, 5, 10)
    ]

    captured: list[DiscoveredContent] = []

    async def fake_serve(profile, candidates, **kwargs):
        captured.extend(candidates)
        # Mirror what the real engine does:
        # confidence = item.relevance_score
        return [
            Recommendation(
                content=item,
                expression=f"rec for {item.content_id}",
                topic_label="t",
                confidence=item.relevance_score,
                presented=False,
            )
            for item in candidates
        ]

    mock_engine = MagicMock()
    mock_engine.serve_external_candidates = AsyncMock(side_effect=fake_serve)

    with (
        patch.object(recommender, "build_recommender", return_value=mock_engine),
        patch.object(recommender, "fetch_candidates", return_value=articles),
    ):
        spec = recommender.load_users(users_p)[0]
        result = recommender.run_one_user(spec, data_dir=tmp_path / "runtime", limit=5)

    # Adapter received the rank and mapped it to relevance_score.
    assert len(captured) == 4
    by_rank = {item.source_rank: item for item in captured}
    assert by_rank[1].relevance_score == 1.0
    assert by_rank[2].relevance_score == 0.5
    assert by_rank[5].relevance_score == 0.2
    assert by_rank[10].relevance_score == 0.1

    # Confidence on the output reflects the rank-derived relevance_score.
    confidences = [r["confidence"] for r in result["recommendations"]]
    assert all(c > 0.0 for c in confidences), confidences
    assert max(confidences) == pytest.approx(1.0)


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


def _build_search_spec() -> user_profile.UserSpec:
    """Spec with 5 interests of different weights for ordering tests."""
    return user_profile.UserSpec(
        user_id="u1",
        display_name="U1",
        interests=[
            user_profile.InterestSpec("a", "x", 0.5),
            user_profile.InterestSpec("b", "x", 0.9),
            user_profile.InterestSpec("c", "x", 0.7),
            user_profile.InterestSpec("d", "x", 0.3),
            user_profile.InterestSpec("e", "x", 0.8),
        ],
        disliked_topics=[],
    )


def test_fetch_candidates_invokes_search_on_top_k_interests() -> None:
    """When use_search=True and the provider supports search, fetch_candidates
    calls search() once per top-K interest on each search-enabled provider.
    """
    spec = _build_search_spec()
    search_calls: list[tuple[str, str]] = []

    class FakeProvider:
        def __init__(self) -> None:
            self.platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem("h1", "https://hot.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            search_calls.append((self.platform, keyword))
            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem(f"s-{keyword}", f"https://s.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()

    with patch.object(
        recommender,
        "_build_provider",
        return_value=(FakeProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=3,
            search_results_per_interest=5,
        )

    # Top-3 interests by weight: b (0.9), e (0.8), c (0.7) — order within
    # a sorted slice is stable but we just check the set, not the order.
    keywords = {kw for _, kw in search_calls}
    assert keywords == {"b", "e", "c"}
    assert len(search_calls) == 3
    # Hot-list article + 3 search articles, all distinct URLs.
    urls = [a["url"] for a in articles]
    assert len(urls) == 4
    assert len(set(urls)) == 4
    # Search results carry the interest name they were returned for.
    search_articles = [a for a in articles if a.get("search_query")]
    assert len(search_articles) == 3
    assert {a["search_query"] for a in search_articles} == {"b", "e", "c"}


def test_fetch_candidates_dedups_overlap_between_hot_list_and_search() -> None:
    """If the same URL appears in both passes it must be returned once."""
    spec = _build_search_spec()
    shared_url = "https://shared.com/x"

    class FakeProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem("shared", shared_url),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem("shared", shared_url, title="dup"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender,
        "_build_provider",
        return_value=(FakeProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=1,
        )

    urls = [a["url"] for a in articles]
    assert urls == [shared_url], f"expected exactly one entry for {shared_url}, got {urls}"
    # Hot-list wins (it ran first) — no search_query field.
    assert "search_query" not in articles[0]


def test_fetch_candidates_isolates_search_failure() -> None:
    """A single (provider, interest) pair raising must not crash the fetch;
    other pairs still contribute articles."""
    spec = user_profile.UserSpec(
        user_id="u1",
        display_name="U1",
        interests=[
            user_profile.InterestSpec("good", "x", 0.9),
            user_profile.InterestSpec("bad", "x", 0.8),
        ],
        disliked_topics=[],
    )

    class PartialFailProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem("h", "https://hot.com/h"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            if keyword == "bad":
                raise RuntimeError("synthetic search failure")
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem(f"good-{keyword}", f"https://g.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender,
        "_build_provider",
        return_value=(PartialFailProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=2,
        )

    # Hot + 1 search = 2 articles. The 'bad' keyword raise is logged & skipped.
    assert len(articles) == 2
    search_articles = [a for a in articles if a.get("search_query")]
    assert [a["search_query"] for a in search_articles] == ["good"]


def test_fetch_candidates_use_search_false_skips_search_pass() -> None:
    """Passing use_search=False must not call provider.search at all."""
    spec = _build_search_spec()
    search_called = False

    class FakeProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem("h", "https://h.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            nonlocal search_called
            search_called = True
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender,
        "_build_provider",
        return_value=(FakeProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec, providers=["toutiao"], use_search=False
        )
    assert not search_called
    assert len(articles) == 1
    assert "search_query" not in articles[0]


def test_fetch_candidates_search_only_runs_on_enabled_providers() -> None:
    """If a search-capable provider is NOT in the user's enabled list, its
    search() must not be called. Use ``providers`` as the gating list.
    """
    spec = _build_search_spec()
    toutiao_called = {"search": 0}

    class ToutiaoOnly:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem("h", "https://t.com/1"),),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            toutiao_called["search"] += 1
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem(f"s-{keyword}", f"https://t.com/s/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender,
        "_build_provider",
        return_value=(ToutiaoOnly(), fake_client),
    ):
        # Only toutiao enabled; sina_news/thepaper/zhihu_daily search must skip.
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=2,
        )
    assert toutiao_called["search"] == 2
    # 1 hot + 2 search = 3 articles.
    assert len(articles) == 3


def test_is_hot_relevant_keyword_match() -> None:
    interests = [user_profile.InterestSpec("非遗", "x", 0.9)]
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
    assert recommender._is_hot_relevant(relevant, interests) is True
    assert recommender._is_hot_relevant(irrelevant, interests) is False
    assert recommender._is_hot_relevant(
        {"title": "", "body_text": "", "summary": ""}, interests
    ) is False
    assert (
        recommender._is_hot_relevant(
            {"title": "x", "body_text": "y", "summary": ""}, []
        )
        is False
    )


def test_fetch_candidates_prefer_search_drops_irrelevant_hot_when_search_yields_plenty() -> None:
    """When search produces many items (>= target_limit * 4), prefer_search
    must drop ALL hot items regardless of relevance. Rationale: the user
    explicitly said 'if hot didn't match, replace with search entirely'.
    """
    spec = _build_search_spec()

    class ManySearchProvider:
        platform = "toutiao"

        def __init__(self) -> None:
            pass

        def collect_hot_list(self, collected_at):
            # Three hot items, NONE mentioning any user interest
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(
                    _make_hotitem("h1", "https://hot.com/h1", title="军事新闻"),
                    _make_hotitem("h2", "https://hot.com/h2", title="南海局势"),
                    _make_hotitem("h3", "https://hot.com/h3", title="台风快讯"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "zzz",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
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
        recommender,
        "_build_provider",
        return_value=(ManySearchProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=3,
            target_limit=5,
            prefer_search=True,
        )

    # 3 interests × 5 (capped by search_results_per_interest) = 15 search
    # < plenty (20), so the "enough" branch runs. Since none of the hot
    # items mention any interest keyword, relevant_hot = [] and only the
    # 15 search items are returned.
    urls = [a["url"] for a in articles]
    assert all("hot.com" not in u for u in urls), urls
    assert all(a.get("search_query") for a in articles)
    assert len(articles) == 15


def test_fetch_candidates_prefer_search_drops_hot_when_search_far_exceeds_plenty() -> None:
    """If search results per interest are bumped above plenty, the
    plenty-branch drops ALL hot — proves the > 4× threshold works.
    """
    spec = _build_search_spec()

    class Provider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(
                    _make_hotitem("h1", "https://hot.com/h1", title="zzz"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(item.item_id, "zzz", "full_text", "", collected_at, item.url, "success")

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=tuple(
                    _make_hotitem(f"{keyword}-{i}", f"https://s.com/{i}", title="zzz")
                    for i in range(20)
                ),
                metadata={},
            )

    fake = MagicMock()
    with patch.object(recommender, "_build_provider", return_value=(Provider(), fake)):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=3,
            target_limit=5,
            search_results_per_interest=20,  # 3 × 20 = 60 > plenty(20) pre-dedup
            prefer_search=True,
        )
    # Plenty branch: hot is fully dropped.
    urls = [a["url"] for a in articles]
    assert all("hot.com" not in u for u in urls), urls
    # After URL dedup across 3 interests × 20 same-prefix URLs, exactly
    # 20 unique search items remain.
    assert len(articles) == 20


def test_fetch_candidates_prefer_search_backfills_when_search_is_thin() -> None:
    """When search is thin (< target_limit), backfill with relevant hot
    items first; tail-fill with other_hot to reach the engine's pool size.
    """
    spec = user_profile.UserSpec(
        user_id="u1",
        display_name="U1",
        interests=[user_profile.InterestSpec("非遗", "x", 0.9)],
        disliked_topics=[],
    )

    class ThinSearchProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(
                    _make_hotitem("h_relevant_1", "https://r.com/1", title="非遗手工"),
                    _make_hotitem(
                        "h_relevant_2", "https://r.com/2", title="老手艺传承"
                    ),
                    _make_hotitem("h_other_1", "https://o.com/1", title="军事新闻"),
                    _make_hotitem("h_other_2", "https://o.com/2", title="南海局势"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(
                    _make_hotitem(
                        "s1", "https://search.com/1", title=f"{keyword}第1篇"
                    ),
                ),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender,
        "_build_provider",
        return_value=(ThinSearchProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=1,
            target_limit=5,
            prefer_search=True,
        )

    # Search thin (only 1 hit) → backfill with relevant_hot first, then
    # other_hot to reach ~40 candidates.
    urls = [a["url"] for a in articles]
    search_urls = [u for u in urls if "search.com" in u]
    relevant_hot_urls = [u for u in urls if "r.com" in u]
    other_hot_urls = [u for u in urls if "o.com" in u]
    # 1 search + 2 relevant_hot + ≥1 other_hot = at least 4
    assert len(search_urls) == 1
    assert len(relevant_hot_urls) == 2
    assert len(other_hot_urls) >= 1
    # The search article must come first in the returned list.
    assert urls[0].endswith("/search.com/1")


def test_fetch_candidates_no_prefer_search_keeps_all_hot() -> None:
    """With prefer_search=False, the V3 merge behavior (all hot + all
    search, dedup'd by URL) is preserved.
    """
    spec = _build_search_spec()

    class AllProvider:
        platform = "toutiao"

        def collect_hot_list(self, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(
                    _make_hotitem("h1", "https://hot.com/h1", title="军事新闻"),
                    _make_hotitem("h2", "https://hot.com/h2", title="南海局势"),
                ),
                metadata={},
            )

        def fetch_detail(self, item, collected_at):
            return ItemDetail(
                item.item_id,
                "body",
                "full_text",
                "",
                collected_at,
                item.url,
                "success",
            )

        def search(self, keyword, page, page_size, collected_at):
            from heated_topics_v3.providers.common import ProviderCapture

            return ProviderCapture(
                raw_text="",
                raw_suffix="",
                items=(_make_hotitem(f"s-{keyword}", f"https://s.com/{keyword}"),),
                metadata={},
            )

    fake_client = MagicMock()
    with patch.object(
        recommender,
        "_build_provider",
        return_value=(AllProvider(), fake_client),
    ):
        articles = recommender.fetch_candidates(
            spec,
            providers=["toutiao"],
            search_top_k=3,
            prefer_search=False,
        )

    # 2 hot + 3 search = 5 (all).
    assert len(articles) == 5
    hot_urls = [a["url"] for a in articles if "hot.com" in a["url"]]
    assert len(hot_urls) == 2
