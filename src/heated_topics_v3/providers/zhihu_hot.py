"""Authenticating provider for the zhihu.com official hot board.

The provider requires a local ``ZHIHU_COOKIE`` env value supplied by the user.
It never falls back to anonymous access and never proxies the credential to
any host outside the trust list.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
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

_HOT_SCORE_RE = re.compile(r"([\d.]+)\s*(万|亿)?\s*热度")
_HOT_MULTIPLIERS = {"": 1, "万": 10_000, "亿": 100_000_000}


def parse_hot_score(label: str) -> int | None:
    match = _HOT_SCORE_RE.search(label)
    if match is None:
        return None
    try:
        return int(Decimal(match.group(1)) * _HOT_MULTIPLIERS[match.group(2) or ""])
    except (InvalidOperation, KeyError):
        return None


def _hot_item(
    *,
    question_id: object,
    title: object,
    summary: object,
    url: object,
    heat_label: object,
    rank: int,
    collected_at: str,
) -> HotItem | None:
    identifier = str(question_id or "").strip()
    clean_title = str(title or "").strip()
    clean_url = str(url or "").strip()
    score = parse_hot_score(str(heat_label or ""))
    if not identifier.isdigit() or not clean_title or score is None or score <= 0:
        return None
    expected = f"https://www.zhihu.com/question/{identifier}"
    if clean_url.startswith("/"):
        clean_url = "https://www.zhihu.com" + clean_url
    if clean_url != expected:
        clean_url = expected
    return HotItem(
        item_id=f"zhihu_hot_question_{identifier}",
        platform="zhihu_hot",
        title=clean_title,
        url=clean_url,
        rank=rank,
        heat=HeatMetrics(
            value=score,
            label=str(heat_label or "").strip(),
            metric_name="hot_score",
            metrics={"hot_score": score},
        ),
        summary=str(summary or "").strip(),
        publication_time=None,
        collected_at=collected_at,
        raw_payload={"question_id": identifier},
    )


def parse_api_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ProviderContractError("zhihu hot API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ProviderContractError("zhihu hot API envelope invalid")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ProviderContractError("zhihu hot API data missing")

    items: list[HotItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        target = row.get("target")
        if not isinstance(target, dict):
            continue
        title_area = target.get("title_area")
        excerpt_area = target.get("excerpt_area")
        metrics_area = target.get("metrics_area")
        link = target.get("link")
        if not all(
            isinstance(value, dict)
            for value in (title_area, excerpt_area, metrics_area, link)
        ):
            continue
        item = _hot_item(
            question_id=target.get("id"),
            title=title_area.get("text"),
            summary=excerpt_area.get("text"),
            url=link.get("url"),
            heat_label=metrics_area.get("text"),
            rank=len(items) + 1,
            collected_at=collected_at,
        )
        if item is not None:
            items.append(item)

    if not items:
        raise ProviderContractError("zhihu hot API produced no items")
    return tuple(items)


def _extract_hydration_hot_list(raw: str) -> list[dict[str, object]]:
    pattern = re.compile(
        r'<script[^>]*id="js-initialData"[^>]*>\s*({.*?})\s*</script>',
        re.DOTALL,
    )
    match = pattern.search(raw)
    if match is None:
        return []
    try:
        parsed = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    initial = parsed.get("initialState") if isinstance(parsed, dict) else None
    topstory = initial.get("topstory") if isinstance(initial, dict) else None
    rows = topstory.get("hotList") if isinstance(topstory, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


class _HotHtmlParser(HTMLParser):
    """Bounded HTML fallback used when the hydration JSON is absent."""

    def __init__(self, collected_at: str) -> None:
        super().__init__()
        self.collected_at = collected_at
        self._in_section = False
        self._question_id: str | None = None
        self._href: str | None = None
        self._title_parts: list[str] = []
        self._summary_parts: list[str] = []
        self._score_label = ""
        self._in_title = False
        self._in_summary = False
        self._rank_text = ""
        self._in_rank = False
        self._in_score = False
        self.items: list[HotItem] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "section" and attrs_dict.get("data-za-detail-view-path-module") == "HotItem":
            self._in_section = True
            self._question_id = None
            self._href = None
            self._title_parts = []
            self._summary_parts = []
            self._score_label = ""
            self._rank_text = ""
            self._in_title = False
            self._in_summary = False
            self._in_rank = False
            self._in_score = False
            return
        if not self._in_section:
            return
        classes = (attrs_dict.get("class") or "").split()
        if tag == "span" and "HotItem-rank" in classes:
            self._in_rank = True
            return
        if tag == "a" and self._question_id is None:
            href = attrs_dict.get("href", "")
            m = re.match(r"^/question/(\d+)", href)
            if m:
                self._question_id = m.group(1)
                self._href = href
                self._in_title = True
            return
        if tag == "h2":
            self._in_title = True
            return
        if tag == "p":
            self._in_summary = True
            return
        if tag == "span" and not self._score_label:
            self._in_score = True

    def handle_endtag(self, tag):
        if not self._in_section:
            return
        if tag == "section":
            self._finalize_section()
            self._in_section = False
            return
        if tag == "h2":
            self._in_title = False
        elif tag == "p":
            self._in_summary = False
        elif tag == "span":
            self._in_rank = False
            self._in_score = False

    def handle_data(self, data):
        if not self._in_section:
            return
        text = data.strip()
        if not text:
            return
        if self._in_rank:
            self._rank_text += text
        elif self._in_title:
            self._title_parts.append(text)
        elif self._in_summary:
            self._summary_parts.append(text)
        elif self._in_score and parse_hot_score(text) is not None:
            self._score_label = text

    def _finalize_section(self):
        rank_value = int(self._rank_text) if self._rank_text.isdigit() else len(self.items) + 1
        item = _hot_item(
            question_id=self._question_id,
            title="".join(self._title_parts).strip(),
            summary=" ".join(self._summary_parts).strip(),
            url=self._href,
            heat_label=self._score_label,
            rank=rank_value,
            collected_at=self.collected_at,
        )
        if item is not None:
            self.items.append(item)


def parse_html_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
    rows = _extract_hydration_hot_list(raw)
    if rows:
        items: list[HotItem] = []
        for row in rows:
            item = _hot_item(
                question_id=row.get("id"),
                title=row.get("title"),
                summary=row.get("excerpt"),
                url=row.get("url"),
                heat_label=row.get("detailText"),
                rank=len(items) + 1,
                collected_at=collected_at,
            )
            if item is not None:
                items.append(item)
    else:
        parser = _HotHtmlParser(collected_at)
        parser.feed(raw)
        items = parser.items

    if not items:
        raise ProviderContractError("zhihu hot HTML produced no items")
    return tuple(items)


class ZhihuHotProvider:
    platform = "zhihu_hot"
    supports_search = False
    weights: Mapping[str, float] = {"hot_score": 1.0}
    absolute_floors: Mapping[str, float] = {"hot_score": 1.0}

    parse_api_hot_list = staticmethod(parse_api_hot_list)
    parse_html_hot_list = staticmethod(parse_html_hot_list)

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
        api = self._get(ZHIHU_HOT_API_URL)
        try:
            items = parse_api_hot_list(api.text, collected_at)
        except ProviderContractError:
            page = self._get(ZHIHU_HOT_PAGE_URL)
            items = parse_html_hot_list(page.text, collected_at)
            return ProviderCapture(
                page.text, ".html", items, metadata={"source": "html_fallback"}
            )
        return ProviderCapture(api.text, ".json", items, metadata={"source": "api"})

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
