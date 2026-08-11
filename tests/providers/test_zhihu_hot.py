"""Offline tests for the authenticated zhihu_hot provider."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-25T12:00:00+08:00"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_missing_cookie_has_explicit_health_status():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(_client(lambda request: httpx.Response(500)), "")
    assert provider.check_auth() == "missing"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_http_failures_are_expired_without_leaking_cookie(status):
    from heated_topics_v3.providers.common import AuthenticationExpiredError
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    cookie = "z_c0=private-cookie-value"
    provider = ZhihuHotProvider(
        _client(lambda request: httpx.Response(status, request=request)),
        cookie,
    )

    with pytest.raises(AuthenticationExpiredError) as captured:
        provider.collect_hot_list(NOW)
    assert cookie not in str(captured.value)
    assert provider.check_auth() == "expired"


def test_signin_redirect_is_expired():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "/signin?next=%2Fhot"},
            request=request,
        )

    provider = ZhihuHotProvider(_client(handler), "z_c0=local")
    assert provider.check_auth() == "expired"


def test_signin_html_is_expired():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    signin = (FIXTURES / "zhihu_hot_signin.html").read_text(encoding="utf-8")
    provider = ZhihuHotProvider(
        _client(
            lambda request: httpx.Response(
                200, text=signin, request=request,
                headers={"Content-Type": "text/html"},
            )
        ),
        "z_c0=local",
    )
    assert provider.check_auth() == "expired"


def test_rate_limit_is_reported_as_blocked():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(
        _client(lambda request: httpx.Response(429, request=request)),
        "z_c0=local",
    )
    assert provider.check_auth() == "blocked"


def test_provider_never_sends_cookie_to_untrusted_host():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(_client(lambda request: httpx.Response(200)), "z_c0=local")
    with pytest.raises(ValueError, match="untrusted zhihu URL"):
        provider._get("https://example.com/article")


def test_transient_gateway_failure_retries_once():
    from heated_topics_v3.providers.zhihu_hot import (
        ZHIHU_HOT_API_URL,
        ZhihuHotProvider,
    )

    calls = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text='{"data":[]}', request=request)

    provider = ZhihuHotProvider(_client(handler), "z_c0=local")
    assert provider._get(ZHIHU_HOT_API_URL).status_code == 200
    assert calls == 2


def test_zhihu_hot_provider_contract_attributes():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    provider = ZhihuHotProvider(_client(lambda request: httpx.Response(500)), "")
    assert provider.platform == "zhihu_hot"
    assert provider.supports_search is False
    assert provider.weights == {"hot_score": 1.0}
    assert provider.absolute_floors == {"hot_score": 1.0}


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_hot_score_parses_chinese_units():
    from heated_topics_v3.providers.zhihu_hot import parse_hot_score

    assert parse_hot_score("2114 万热度") == 21_140_000
    assert parse_hot_score("1.2 亿热度") == 120_000_000
    assert parse_hot_score("9876 热度") == 9_876
    assert parse_hot_score("没有热度") is None


def test_api_and_html_hot_lists_have_same_contract():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    api = ZhihuHotProvider.parse_api_hot_list(
        _fixture("zhihu_hot_api.json"), NOW
    )
    html = ZhihuHotProvider.parse_html_hot_list(
        _fixture("zhihu_hot_page.html"), NOW
    )

    projection = lambda items: [
        (
            item.item_id,
            item.title,
            item.url,
            item.rank,
            item.heat.value,
            item.summary,
        )
        for item in items
    ]
    assert projection(api) == projection(html)
    assert api[0].item_id == "zhihu_hot_question_2064289475916560021"
    assert api[0].heat.metrics == {"hot_score": 21_140_000}


def test_collect_uses_api_when_contract_is_valid():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=_fixture("zhihu_hot_api.json"), request=request)

    capture = ZhihuHotProvider(_client(handler), "z_c0=local").collect_hot_list(NOW)
    assert capture.metadata == {"source": "api"}
    assert capture.raw_suffix == ".json"
    assert len(capture.items) == 2
    assert len(calls) == 1


def test_api_parser_accepts_current_scalar_target_shape():
    from heated_topics_v3.providers.zhihu_hot import parse_api_hot_list

    raw = json.dumps({
        "data": [{
            "target": {
                "id": 2069064416709063399,
                "title": "heritage and local life",
                "url": "https://api.zhihu.com/questions/2069064416709063399",
                "excerpt": "local customs and traditional crafts",
            },
            "detail_text": "1183 热度",
        }]
    })
    items = parse_api_hot_list(raw, NOW)
    assert len(items) == 1
    assert items[0].title == "heritage and local life"
    assert items[0].heat.value == 1183


def test_collect_falls_back_to_html_only_on_api_contract_change():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        body = "{}" if request.url.path.startswith("/api/") else _fixture("zhihu_hot_page.html")
        return httpx.Response(200, text=body, request=request)

    capture = ZhihuHotProvider(_client(handler), "z_c0=local").collect_hot_list(NOW)
    assert capture.metadata == {"source": "html_fallback"}
    assert capture.raw_suffix == ".html"
    assert calls == ["/api/v3/feed/topstory/hot-lists/total", "/hot"]


@pytest.mark.parametrize("raw", ["{}", '{"data":[]}', '{"data":[{"target":{}}]}'])
def test_api_parser_fails_closed(raw):
    from heated_topics_v3.providers.common import ProviderContractError
    from heated_topics_v3.providers.zhihu_hot import parse_api_hot_list

    with pytest.raises(ProviderContractError):
        parse_api_hot_list(raw, NOW)


import json


def _hot_item():
    from heated_topics_v3.providers.zhihu_hot import parse_api_hot_list

    return parse_api_hot_list(_fixture("zhihu_hot_api.json"), NOW)[0]


def test_question_api_builds_full_text_and_metadata():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/answers"):
            body = _fixture("zhihu_hot_answers.json")
        else:
            body = _fixture("zhihu_hot_question.json")
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )

    assert detail.content_status == "full_text"
    assert "问题描述" in detail.content
    assert "热门回答 1" in detail.content
    assert "热门回答 2" in detail.content
    assert detail.metadata["question"] == {
        "question_id": "2064289475916560021",
        "follower_count": 1465,
        "view_count": 1985997,
        "answer_count": 583,
    }
    assert detail.metadata["answers"][0]["author"] == "示例作者甲"
    assert detail.metadata["answers"][0]["voteup_count"] == 1551


def test_question_detail_caps_answers_at_five():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    answers = json.loads(_fixture("zhihu_hot_answers.json"))
    answers["data"] = answers["data"] * 4

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.dumps(answers, ensure_ascii=False)
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert len(detail.metadata["answers"]) == 5


def test_question_api_contract_change_falls_back_to_html():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            _fixture("zhihu_hot_question_page.html")
            if request.url.path.startswith("/question/")
            else "{}"
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success:html_fallback"
    assert len(detail.metadata["answers"]) == 1
    assert detail.metadata["answers"][0]["favorite_count"] == 276
    assert detail.metadata["answers"][0]["like_count"] == 27


def test_short_answer_is_skipped_but_question_can_still_qualify():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    answers = json.loads(_fixture("zhihu_hot_answers.json"))
    answers["data"][0]["content"] = "<p>太短。</p>"

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.dumps(answers, ensure_ascii=False)
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert all(
        answer["answer_id"] != "2064295804840547334"
        for answer in detail.metadata["answers"]
    )


def test_question_without_answers_is_partial_if_description_qualifies():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            '{"data":[],"paging":{"is_end":true}}'
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), "z_c0=local").fetch_detail(
        _hot_item(), NOW
    )
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "partial:no_answers"
    assert detail.metadata["answers"] == []


def test_detail_metadata_contains_no_cookie():
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    cookie = "z_c0=private-cookie-value"
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            _fixture("zhihu_hot_answers.json")
            if request.url.path.endswith("/answers")
            else _fixture("zhihu_hot_question.json")
        )
        return httpx.Response(200, text=body, request=request)

    detail = ZhihuHotProvider(_client(handler), cookie).fetch_detail(_hot_item(), NOW)
    assert cookie not in json.dumps(detail.metadata, ensure_ascii=False)
    assert cookie not in detail.content


def test_zhihu_hot_rank_articles_orders_by_view_count_then_rank_then_hot_score():
    from dataclasses import replace
    from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

    item_a = parse_api_hot_list(_fixture("zhihu_hot_api.json"), NOW)[0]
    item_b = parse_api_hot_list(_fixture("zhihu_hot_api.json"), NOW)[1]
    item_a_view = 10_000_000
    item_b_view = 1_000_000

    article_a = _make_article(item_a, view_count=item_a_view)
    article_b = _make_article(item_b, view_count=item_b_view)

    provider = ZhihuHotProvider(_client(lambda r: httpx.Response(200)), "z_c0=local")
    ordered = provider.rank_articles([article_b, article_a])
    assert ordered[0].hot_item.item_id == article_a.hot_item.item_id


def parse_api_hot_list(raw, collected_at):
    from heated_topics_v3.providers.zhihu_hot import parse_api_hot_list as _parse

    return _parse(raw, collected_at)


def _make_article(hot_item, view_count):
    from heated_topics_v3.contracts import (
        ContentValidation,
        HeatEvidence,
        ItemDetail,
        QualifiedArticle,
    )

    detail = ItemDetail(
        item_id=hot_item.item_id,
        content="问题描述\n\n第一段热门回答正文。\n\n第二段热门回答正文。",
        content_status="full_text",
        publication_time=None,
        collected_at=NOW,
        source_url=hot_item.url,
        fetch_status="success",
        metadata={
            "question": {
                "question_id": str(hot_item.raw_payload.get("question_id", "")),
                "follower_count": 100,
                "view_count": view_count,
                "answer_count": 1,
            },
            "answers": [],
        },
    )
    return QualifiedArticle(
        hot_item=hot_item,
        detail=detail,
        heat_evidence=HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=hot_item.rank,
            native_hot_value=float(hot_item.heat.value or 0),
            metrics={"hot_score": float(hot_item.heat.value or 0)},
            threshold_metrics={"hot_score": 1.0},
            qualified_by=("official_hot_board",),
        ),
        content_validation=ContentValidation(
            status="accepted",
            parser="zhihu_question",
            character_count=100,
            paragraph_count=3,
            reasons=(),
        ),
        platform_heat_score=0.0,
    )
