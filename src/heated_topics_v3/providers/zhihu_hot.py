"""Authenticating provider for the zhihu.com official hot board.

The provider requires a local ``ZHIHU_COOKIE`` env value supplied by the user.
It never falls back to anonymous access and never proxies the credential to
any host outside the trust list.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from heated_topics_v3.content import validate_full_text

from .common import (
    AuthenticationBlockedError,
    AuthenticationExpiredError,
    MissingCredentialError,
    ProviderCapture,
    ProviderContractError,
)


ZHIHU_COOKIE_ENV = "ZHIHU_COOKIE"
ZHIHU_HOT_API_URL = (
    "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"
    "?limit=50&desktop=true"
)
ZHIHU_HOT_PAGE_URL = "https://www.zhihu.com/hot"
TRUSTED_ZHIHU_HOSTS = frozenset({"www.zhihu.com", "zhihu.com"})
TRANSIENT_STATUSES = frozenset({502, 503, 504})
MAX_REQUEST_ATTEMPTS = 2


class ZhihuHotProvider:
    platform = "zhihu_hot"
    supports_search = False
    weights: Mapping[str, float] = {"hot_score": 1.0}
    absolute_floors: Mapping[str, float] = {"hot_score": 1.0}

    def __init__(self, client: httpx.Client, cookie: str):
        self.client = client
        self.cookie = cookie.strip()

    def _get(self, url: str) -> httpx.Response:
        if not self.cookie:
            raise MissingCredentialError(ZHIHU_COOKIE_ENV)
        current = url
        for _redirect in range(4):
            host = (urlsplit(current).hostname or "").casefold()
            if host not in TRUSTED_ZHIHU_HOSTS:
                raise ValueError("untrusted zhihu URL")
            for attempt in range(MAX_REQUEST_ATTEMPTS):
                response = self.client.get(
                    current,
                    follow_redirects=False,
                    headers={
                        "Cookie": self.cookie,
                        "Referer": ZHIHU_HOT_PAGE_URL,
                        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                    },
                )
                if (
                    response.status_code not in TRANSIENT_STATUSES
                    or attempt + 1 == MAX_REQUEST_ATTEMPTS
                ):
                    break
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                current = str(response.url.join(location))
                if urlsplit(current).path.casefold().startswith("/signin"):
                    raise AuthenticationExpiredError(ZHIHU_COOKIE_ENV)
                continue
            if response.status_code in {401, 403}:
                raise AuthenticationExpiredError(ZHIHU_COOKIE_ENV)
            if response.status_code in {418, 429}:
                raise AuthenticationBlockedError(ZHIHU_COOKIE_ENV)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").casefold()
            body = response.text.casefold()
            if (
                "text/html" in content_type
                and "/signin" in body
                and ("登录" in response.text or "sign in" in body)
            ):
                raise AuthenticationExpiredError(ZHIHU_COOKIE_ENV)
            return response
        raise ProviderContractError("zhihu redirect limit exceeded")

    def check_auth(
        self,
    ) -> Literal["valid", "missing", "expired", "blocked", "contract_changed"]:
        if not self.cookie:
            return "missing"
        try:
            self.collect_hot_list("1970-01-01T00:00:00+08:00")
        except AuthenticationExpiredError:
            return "expired"
        except AuthenticationBlockedError:
            return "blocked"
        except httpx.HTTPStatusError:
            return "blocked"
        except ProviderContractError:
            return "contract_changed"
        return "valid"

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self._get(ZHIHU_HOT_API_URL)
        raise ProviderContractError("zhihu hot parser not implemented")

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        validate_full_text("", item.title, item.summary, parser="zhihu_question")
        raise ProviderContractError("zhihu hot parser not implemented")

    def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        return ProviderCapture("", ".json", ())

    def enrich_metrics(
        self, items: Any, collected_at: str
    ) -> tuple[HotItem, ...]:
        if not items:
            return ()
        return tuple(items)
