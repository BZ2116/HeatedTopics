"""CLI tests for the three-platform news commands."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from heated_topics_v3.contracts import (
    ContentValidation,
    DailySnapshot,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    PlatformCollectionStatus,
    QualifiedArticle,
    RecommendationBundle,
    UserProfile,
)
from heated_topics_v3.storage import FileRepository


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 23, 8, 1, tzinfo=SHANGHAI)
COLLECTED_AT = NOW.isoformat()
BUSINESS_DATE = "2026-07-23"
KEYWORD = "人工智能"

_LONG_BODY = (
    "正文第一段，介绍事件背景，描述发生时间地点和主要人物，并交代事件起因。\n\n"
    "正文第二段，引用公开信息补充细节，说明各方回应、数据来源与相关证据。\n\n"
    "正文第三段，交待后续安排、影响范围、可能的后续进展与尚需确认的信息。\n\n"
    "正文第四段，提供独立第三方观察和专家评论，对事件的长期影响做简要判断。\n"
)


def _metrics(payload: Mapping[str, float] | None, *, name: str = "comments") -> HeatMetrics:
    payload = dict(payload or {})
    primary = next(iter(payload.values()), None)
    return HeatMetrics(
        value=primary,
        label="" if primary is None else str(primary),
        metric_name=name if payload else "",
        metrics=payload,
    )


def _make_hot_item(
    *,
    platform: str,
    item_id: str,
    rank: int | None,
    title: str,
    summary: str = "",
    metrics: Mapping[str, float] | None = None,
) -> HotItem:
    return HotItem(
        item_id=item_id,
        platform=platform,
        title=title,
        url=f"https://example.test/{platform}/{item_id}",
        rank=rank,
        heat=_metrics(metrics),
        summary=summary,
        publication_time=None,
        collected_at=COLLECTED_AT,
        raw_payload={},
    )


def _build_article(item: HotItem) -> QualifiedArticle:
    detail = ItemDetail(
        item_id=item.item_id,
        content=_LONG_BODY,
        content_status="full_text",
        publication_time=item.publication_time,
        collected_at=COLLECTED_AT,
        source_url=item.url,
        fetch_status="success",
    )
    validation = ContentValidation(
        status="accepted",
        parser="fixture",
        character_count=len(_LONG_BODY),
        paragraph_count=_LONG_BODY.count("\n\n") + 1,
        reasons=(),
    )
    return QualifiedArticle(
        hot_item=item,
        detail=detail,
        heat_evidence=HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=item.rank,
            native_hot_value=float(item.heat.value) if isinstance(item.heat.value, (int, float)) else None,
            metrics={k: float(v) for k, v in item.heat.metrics.items()},
            threshold_metrics={},
            qualified_by=("official_hot_board",),
        ),
        content_validation=validation,
        platform_heat_score=0.0,
    )


def _seed_all_three_platforms(repository: FileRepository, count: int = 5) -> None:
    for platform in ("sina_news", "thepaper", "netease_news"):
        articles = tuple(
            _build_article(
                _make_hot_item(
                    platform=platform,
                    item_id=f"{platform}_{index + 1}",
                    rank=index + 1,
                    title=f"{KEYWORD} {platform} {index + 1}",
                    summary=f"{KEYWORD} 摘要",
                    metrics={"comments": 20.0 + index, "views": 100.0 + index},
                )
            )
            for index in range(count)
        )
        repository.save_eligible(BUSINESS_DATE, platform, articles)
        repository.publish_active_snapshot(platform, BUSINESS_DATE)


def _profile_path(tmp_path: Path) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "user_id": "cli-news",
                "primary_track": "综合新闻",
                "secondary_track": "热榜",
                "persona": "cli news tester",
                "primary_keyword": KEYWORD,
                "updated_at": COLLECTED_AT,
            }
        ),
        encoding="utf-8",
    )
    return path


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_collect_news_emits_machine_readable_status(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli

    observed = {}

    def fake_collect_news(now, repository, providers):
        observed.update(now=now, repository=repository, providers=providers)
        statuses = tuple(
            PlatformCollectionStatus(platform, "success", now.isoformat(), 30)
            for platform in ("sina_news", "thepaper", "netease_news")
        )
        return DailySnapshot(
            now.date().isoformat(),
            now.isoformat(),
            {platform: () for platform in ("sina_news", "thepaper", "netease_news")},
            statuses,
        )

    monkeypatch.setattr(cli, "collect_news_daily", fake_collect_news)

    exit_code = cli.main(["collect-news", "--data-root", str(tmp_path)])

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["status"] == "success"
    assert payload["command"] == "collect-news"
    assert payload["platforms"] == [
        "sina_news",
        "thepaper",
        "netease_news",
        "baidu_hot",
        "zhihu_daily",
    ]
    assert payload["business_date"] == observed["now"].date().isoformat()
    assert payload["data_root"] == str(tmp_path.resolve())
    assert set(observed["providers"]) == {
        "sina_news",
        "thepaper",
        "netease_news",
        "baidu_hot",
        "zhihu_daily",
    }


def test_collect_news_uses_only_anonymous_headers(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli
    import httpx

    captured_headers: dict[str, str] = {}

    class _SpyTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.update({key: value for key, value in request.headers.items()})
            return httpx.Response(200, text="{}")

    def fake_collect_news(now, repository, providers):
        for provider in providers.values():
            inner_client = getattr(provider, "client", None)
            if inner_client is not None:
                inner_client._transport = _SpyTransport()
        statuses = tuple(
            PlatformCollectionStatus(platform, "success", now.isoformat(), 5)
            for platform in ("sina_news", "thepaper", "netease_news")
        )
        return DailySnapshot(
            now.date().isoformat(),
            now.isoformat(),
            {platform: () for platform in ("sina_news", "thepaper", "netease_news")},
            statuses,
        )

    monkeypatch.setattr(cli, "collect_news_daily", fake_collect_news)

    exit_code = cli.main(["collect-news", "--data-root", str(tmp_path)])

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["command"] == "collect-news"
    assert captured_headers == {} or all(
        "cookie" not in key.casefold() for key in captured_headers
    )


def test_generate_news_cli_does_not_send_cookie(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli
    import httpx

    captured_headers: dict[str, str] = {}

    class _SpyTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.update({key: value for key, value in request.headers.items()})
            return httpx.Response(200, text="{}")

    profile_path = _profile_path(tmp_path)
    repository = FileRepository(tmp_path / "data")
    _seed_all_three_platforms(repository)

    def fake_generate(profile, now, repository_arg, providers):
        for provider in providers.values():
            inner_client = getattr(provider, "client", None)
            if inner_client is not None:
                inner_client._transport = _SpyTransport()
        bundle = RecommendationBundle(
            status="generated",
            user_id=profile.user_id,
            business_date=now.date().isoformat(),
            generated_at=now.isoformat(),
            recommendations=(),
            potential_topics=(),
            general_fallback=(),
            query_metadata={"platforms": {}},
        )
        return bundle

    monkeypatch.setattr(cli, "generate_news_user_result", fake_generate)

    exit_code = cli.main(
        [
            "generate-news",
            "--data-root",
            str(tmp_path / "data"),
            "--profile",
            str(profile_path),
        ]
    )

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["command"] == "generate-news"
    assert payload["status"] == "generated"
    if captured_headers:
        assert all("cookie" not in key.casefold() for key in captured_headers)


def test_generate_news_emits_machine_readable_status(monkeypatch, tmp_path, capsys):
    from heated_topics_v3 import cli

    profile_path = _profile_path(tmp_path)
    observed = {}

    def fake_generate(profile, now, repository, providers):
        observed.update(profile=profile, now=now, repository=repository)
        bundle = RecommendationBundle(
            status="generated",
            user_id=profile.user_id,
            business_date=now.date().isoformat(),
            generated_at=now.isoformat(),
            recommendations=(),
            potential_topics=(),
            general_fallback=(),
            query_metadata={"platforms": {}},
        )
        return bundle

    monkeypatch.setattr(cli, "generate_news_user_result", fake_generate)

    exit_code = cli.main(
        [
            "generate-news",
            "--data-root",
            str(tmp_path / "data"),
            "--profile",
            str(profile_path),
        ]
    )

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["status"] == "generated"
    assert payload["command"] == "generate-news"
    assert payload["user_id"] == "cli-news"
    assert payload["business_date"] == observed["now"].date().isoformat()
    assert observed["profile"].primary_keyword == KEYWORD


def test_generate_news_reuses_same_day_result_without_search(
    monkeypatch, tmp_path, capsys
):
    from heated_topics_v3 import cli

    profile_path = _profile_path(tmp_path)
    repository = FileRepository(tmp_path / "data")
    _seed_all_three_platforms(repository, count=5)

    search_calls: dict[str, int] = {}

    def fake_generate(profile, now, repository, providers):
        for platform, provider in providers.items():
            search_calls[platform] = search_calls.get(platform, 0) + len(
                getattr(provider, "search_calls", [])
            )
        bundle = RecommendationBundle(
            status="generated",
            user_id=profile.user_id,
            business_date=now.date().isoformat(),
            generated_at=now.isoformat(),
            recommendations=(),
            potential_topics=(),
            general_fallback=(),
            query_metadata={"platforms": {}},
        )
        return bundle

    monkeypatch.setattr(cli, "generate_news_user_result", fake_generate)

    first = cli.main(
        [
            "generate-news",
            "--data-root",
            str(tmp_path / "data"),
            "--profile",
            str(profile_path),
        ]
    )
    snapshot = dict(search_calls)
    second = cli.main(
        [
            "generate-news",
            "--data-root",
            str(tmp_path / "data"),
            "--profile",
            str(profile_path),
        ]
    )

    assert first == 0
    assert second == 0
    assert search_calls == snapshot


def test_invalid_news_arguments_return_json_failure(tmp_path, capsys):
    from heated_topics_v3 import cli

    exit_code = cli.main(["collect-news"])

    assert exit_code == 2
    assert _json_output(capsys) == {"status": "failed", "error": "invalid_arguments"}
