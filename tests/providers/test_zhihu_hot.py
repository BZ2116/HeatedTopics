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
