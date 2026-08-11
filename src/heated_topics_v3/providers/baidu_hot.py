"""Strict anonymous Baidu Hot Search official board provider."""

from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from typing import Any, Iterable, Mapping, Sequence
from unicodedata import normalize
from urllib.parse import urljoin, urlsplit

import httpx
from gne import GeneralNewsExtractor

from heated_topics_v3.content import validate_full_text
from heated_topics_v3.contracts import HeatEvidence, HeatMetrics, HotItem, QualifiedArticle

from .common import (
    ProviderCapture,
    ProviderContractError,
    article_text,
    number_or_none,
)


BAIDU_HOT_URL = "https://top.baidu.com/board?tab=realtime"
BAIDU_SEARCH_URL = "https://www.baidu.com/s"
BAIDU_WEIGHTS: dict[str, float] = {"hot_score": 1.0}
BAIDU_ABSOLUTE_FLOORS: dict[str, float] = {"hot_score": 1.0}

_S_DATA = re.compile(r"<!--s-data:(.*?)-->", re.DOTALL)
_LD_JSON = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_MAX_REDIRECT_HOPS = 5


class BaiduHotProvider:
    platform = "baidu_hot"
    weights = BAIDU_WEIGHTS
    absolute_floors = BAIDU_ABSOLUTE_FLOORS

    def __init__(self, client: httpx.Client):
        self.client = client

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(BAIDU_HOT_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".html", self.parse_hot_list(raw, collected_at))

    @staticmethod
    def parse_hot_list(raw_html: str, collected_at: str) -> tuple[HotItem, ...]:
        marker = _S_DATA.search(raw_html)
        if not marker:
            raise ProviderContractError("missing baidu s-data marker")
        try:
            envelope = json.loads(marker.group(1).strip())
        except (TypeError, ValueError) as error:
            raise ProviderContractError("malformed baidu s-data payload") from error
        if not isinstance(envelope, dict):
            raise ProviderContractError("baidu s-data must be a JSON object")

        rows = _resolve_content(envelope)
        if not rows:
            raise ProviderContractError("baidu board has no content rows")

        items: list[HotItem] = []
        for row in rows:
            parsed = _row_to_event(row, collected_at, rank=len(items) + 1)
            if parsed is None:
                continue
            items.append(parsed)
        if not items:
            raise ProviderContractError("baidu board contains no valid hot events")
        return tuple(items)

    def fetch_detail(self, item: HotItem, collected_at: str) -> "ItemDetail":
        resolved_candidates: list[str] = []
        raw_url = (item.raw_payload.get("rawUrl") or item.raw_payload.get("url") or "").strip()
        if raw_url:
            resolved = self._resolve_url(raw_url)
            if resolved and not _is_rejected_surface(resolved):
                resolved_candidates.append(resolved)
        if not resolved_candidates:
            for href in self._search_result_hrefs(item.title, event_title=item.title):
                resolved = self._resolve_url(href)
                if resolved and not _is_rejected_surface(resolved):
                    resolved_candidates.append(resolved)

        for url in resolved_candidates:
            detail = self._detail_from_url(item, url, collected_at)
            if detail is not None:
                return detail
        return ItemDetail(
            item.item_id, "", "rejected", item.publication_time,
            collected_at, item.url, "rejected:no_body",
        )

    def search_with_context(
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
        official_articles: Sequence[QualifiedArticle],
    ) -> ProviderCapture:
        official = tuple(official_articles)
        if not official:
            return ProviderCapture("", ".html", ())

        parent = official[(page - 1) % len(official)].hot_item
        html = self._search_page(parent.title)
        if html is None or _looks_like_captcha(html):
            return ProviderCapture(html or "", ".html", ())

        normalized_keyword = _normalize(keyword)
        results: list[HotItem] = []
        for card in _parse_search_cards(html):
            href = card["href"]
            if not href.lower().startswith(("http://", "https://")):
                continue
            haystack = card["title"] + " " + card["abstract"]
            if normalized_keyword and normalized_keyword not in _normalize(haystack):
                continue
            if not _event_relevant(parent.title, haystack):
                continue
            resolved = self._resolve_url(href)
            if not resolved or _is_rejected_surface(resolved):
                continue
            results.append(_context_item(parent, card, resolved, collected_at))
            if len(results) >= page_size:
                break
        return ProviderCapture(html, ".html", tuple(results))

    def build_search_evidence(
        self, item: HotItem, floors: Mapping[str, float]
    ) -> HeatEvidence | None:
        payload = item.raw_payload
        if "parent_event_id" not in payload:
            return None
        parent_rank = payload.get("parent_rank")
        parent_hot = payload.get("parent_hot_score")
        native = float(parent_hot) if parent_hot is not None else None
        return HeatEvidence(
            source_kind="official_hot_board",
            platform_rank=parent_rank,
            native_hot_value=native,
            metrics={"hot_score": native} if native is not None else {},
            threshold_metrics=dict(floors),
            qualified_by=("official_hot_board",),
        )

    def search(  # pragma: no cover - baidu discovery uses search_with_context
        self,
        keyword: str,
        page: int,
        page_size: int,
        collected_at: str,
    ) -> ProviderCapture:
        return ProviderCapture("", ".html", ())

    def _search_page(self, query: str) -> str | None:
        try:
            response = self.client.get(BAIDU_SEARCH_URL, params={"wd": query})
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        return response.text

    def _search_result_hrefs(self, query: str, *, event_title: str) -> list[str]:
        html = self._search_page(query)
        if html is None or _looks_like_captcha(html):
            return []
        hrefs: list[str] = []
        for card in _parse_search_cards(html):
            href = card["href"]
            if not href.lower().startswith(("http://", "https://")):
                continue
            if not _event_relevant(event_title, card["title"] + " " + card["abstract"]):
                continue
            hrefs.append(href)
        return hrefs

    def _detail_from_url(
        self, item: HotItem, url: str, collected_at: str
    ) -> "ItemDetail | None":
        try:
            html = self.client.get(url).text
        except httpx.HTTPError:
            return None
        content, parser = _extract_public_article(html)
        validation = validate_full_text(content, item.title, item.summary, parser=parser)
        if validation.status != "accepted":
            return None
        return ItemDetail(
            item.item_id, content, "full_text", item.publication_time,
            collected_at, url, "success",
        )

    def _resolve_url(self, url: str, max_hops: int = _MAX_REDIRECT_HOPS) -> str:
        seen: set[str] = set()
        current = url
        for _ in range(max_hops):
            if current in seen:
                return ""
            seen.add(current)
            parsed = urlsplit(current)
            if parsed.scheme.casefold() not in {"http", "https"}:
                return ""
            try:
                response = self.client.get(current)
            except httpx.HTTPError:
                return ""
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                if not location:
                    return ""
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                return ""
            return current
        return ""

    def enrich_metrics(
        self,
        items: Sequence[HotItem],
        collected_at: str,
    ) -> tuple[HotItem, ...]:
        return tuple(items)


def _resolve_content(envelope: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield the hot-event rows from either observed Baidu envelope.

    Accepted shapes:

    * ``{"data": {"cards": [ {"content": [...]} ]}}`` (newer envelope)
    * ``{"cards": [ {"content": [...]} ]}`` (older envelope)

    In both cases, an inner ``content`` list nested inside the first row is
    unwrapped one level so a wrapper row never reaches the row parser.
    """

    for candidate in (
        envelope.get("data", {}).get("cards") if isinstance(envelope.get("data"), dict) else None,
        envelope.get("cards"),
    ):
        if not candidate:
            continue
        for card in candidate:
            if not isinstance(card, dict):
                continue
            content = card.get("content")
            if not isinstance(content, list):
                continue
            if content and isinstance(content[0], dict) and isinstance(content[0].get("content"), list):
                content = content[0]["content"]
            for row in content:
                if isinstance(row, dict):
                    yield row
        return
    return


def _row_to_event(row: dict[str, Any], collected_at: str, *, rank: int) -> HotItem | None:
    title = (row.get("word") or row.get("title") or "").strip()
    query = (row.get("query") or title).strip()
    if not title or not query:
        return None
    hot_score = number_or_none(row.get("hotScore") or row.get("hotTag"))
    if hot_score is None:
        return None
    description = (row.get("desc") or "").strip()
    url = (row.get("rawUrl") or row.get("url") or "").strip()
    item_id = _stable_event_id(query)
    raw_payload = {
        "index": row.get("index"),
        "query": query,
        "rawUrl": row.get("rawUrl"),
        "url": row.get("url"),
        "img": row.get("img"),
        "hotTag": row.get("hotTag"),
        "hotScore": row.get("hotScore"),
    }
    return HotItem(
        item_id=item_id,
        platform="baidu_hot",
        title=title,
        url=url or f"https://top.baidu.com/board?tab=realtime#{item_id}",
        rank=rank,
        heat=HeatMetrics(
            value=int(hot_score),
            label=str(int(hot_score)),
            metric_name="hot_score",
            metrics={"hot_score": float(hot_score)},
        ),
        summary=description,
        publication_time=None,
        collected_at=collected_at,
        raw_payload={k: v for k, v in raw_payload.items() if v not in (None, "")},
    )


def _stable_event_id(query: str) -> str:
    normalized = " ".join(normalize("NFKC", query).casefold().split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"baidu_hot_{digest}"


class _SearchResultParser(HTMLParser):
    """Collect Baidu result-card title, href, and abstract without headers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._depth = 0
        self._in_h3 = False
        self._capture_title = False
        self._in_abstract = False
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        classes = values.get("class", "").split()
        if tag == "div" and "result" in classes and self._depth == 0:
            self._current = {"href": "", "title": "", "abstract": ""}
            self._depth = 1
            return
        if not self._depth:
            return
        if tag == "div":
            self._depth += 1
        elif tag == "h3":
            self._in_h3 = True
        elif tag == "a" and self._in_h3 and self._current is not None and not self._current["href"]:
            self._current["href"] = values.get("href", "")
            self._capture_title = True
        elif tag == "span" and "c-abstract" in classes:
            self._in_abstract = True

    def handle_endtag(self, tag) -> None:
        if not self._depth:
            return
        if tag == "a":
            self._capture_title = False
        elif tag == "h3":
            self._in_h3 = False
        elif tag == "span":
            self._in_abstract = False
        elif tag == "div":
            self._depth -= 1
            if self._depth == 0 and self._current is not None:
                self.cards.append(self._current)
                self._current = None

    def handle_data(self, data) -> None:
        if self._current is None:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_title:
            self._current["title"] += text
        elif self._in_abstract:
            self._current["abstract"] += text


def _parse_search_cards(html: str) -> list[dict[str, str]]:
    parser = _SearchResultParser()
    parser.feed(html)
    return [card for card in parser.cards if card["title"] or card["href"]]


def _looks_like_captcha(html: str) -> bool:
    lowered = html.lower()
    return "百度安全验证" in html or "wappass" in lowered or "verify" in lowered and "captcha" in lowered


def _is_rejected_surface(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if not host:
        return True
    if host.startswith("passport.") or "wappass" in host:
        return True
    if host in {"v.baidu.com", "haokan.baidu.com", "image.baidu.com", "tieba.baidu.com"}:
        return True
    if host.endswith("baidu.com"):
        if path in {"", "/", "/s", "/link", "/baidu", "/board", "/sf"} or path.startswith("/s?"):
            return True
        if path.startswith("/s") and not path.startswith("/static"):
            return True
    return False


def _extract_public_article(html: str) -> tuple[str, str]:
    structured = _json_ld_article_body(html)
    if structured:
        return structured, "json_ld"
    native = article_text(html)
    if native:
        return native, "article"
    try:
        extracted = GeneralNewsExtractor().extract(html)
        content = str(extracted.get("content") or "")
    except Exception:
        content = ""
    return content, "gne"


def _json_ld_article_body(html: str) -> str:
    for match in _LD_JSON.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
        except (TypeError, ValueError):
            continue
        for obj in _iter_ld_objects(data):
            body = obj.get("articleBody")
            if isinstance(body, str) and body.strip():
                return body.strip()
    return ""


def _iter_ld_objects(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if isinstance(item, dict):
                    yield item
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item


def _context_item(
    parent: HotItem, card: dict[str, str], resolved: str, collected_at: str
) -> HotItem:
    url_digest = sha256(resolved.encode("utf-8")).hexdigest()[:16]
    item_id = "baidu_hot_" + sha256(
        f"{parent.item_id}|{url_digest}".encode("utf-8")
    ).hexdigest()[:16]
    payload = {
        "parent_event_id": parent.item_id,
        "parent_event_title": parent.title,
        "parent_rank": parent.rank,
        "parent_hot_score": parent.heat.metrics.get("hot_score"),
        "resolved_url": resolved,
        "query": card["title"],
    }
    return HotItem(
        item_id=item_id,
        platform="baidu_hot",
        title=card["title"],
        url=resolved,
        rank=parent.rank,
        heat=parent.heat,
        summary=card["abstract"],
        publication_time=None,
        collected_at=collected_at,
        raw_payload={k: v for k, v in payload.items() if v not in (None, "")},
    )


def _normalize(text: str) -> str:
    return "".join(normalize("NFKC", text).casefold().split())


def _is_cjk(char: str) -> bool:
    return "一" <= char <= "鿿"


def _cjk_bigrams(text: str) -> set[str]:
    cjk = [char for char in text if _is_cjk(char)]
    return {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}


def _alnum_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 3}


def _event_relevant(event_title: str, candidate_text: str) -> bool:
    event = _normalize(event_title)
    candidate = _normalize(candidate_text)
    if not event or not candidate:
        return False
    if len(event) <= 4 and event in candidate:
        return True
    event_bigrams = _cjk_bigrams(event)
    candidate_bigrams = _cjk_bigrams(candidate)
    if event_bigrams and candidate_bigrams:
        overlap = event_bigrams & candidate_bigrams
        smaller = min(len(event_bigrams), len(candidate_bigrams))
        if len(overlap) >= 2 and smaller and len(overlap) / smaller >= 0.25:
            return True
    if _alnum_tokens(event) & _alnum_tokens(candidate):
        return True
    return False


# Late import to avoid an import cycle with contracts.
from heated_topics_v3.contracts import ItemDetail  # noqa: E402  pylint: disable=wrong-import-position
