"""Strict anonymous The Paper hot-list, search, and detail provider."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Sequence

import httpx
from gne import GeneralNewsExtractor

from heated_topics_v3.content import extract_container_text, validate_full_text
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, ProviderContractError, number_or_none

_BLOCK_RE = re.compile(r"</?(?:p|div|section|h[1-6]|br|li)[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

THEPAPER_HOT_URL = (
    "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"
)
THEPAPER_SEARCH_URL = "https://api.thepaper.cn/search/web/news"
THEPAPER_ARTICLE_URL = "https://www.thepaper.cn/newsDetail_forward_{cont_id}"
THEPAPER_WEIGHTS = {"interaction_num": 0.60, "praise_times": 0.40}
THEPAPER_ABSOLUTE_FLOORS = {"interaction_num": 1.0, "praise_times": 10.0}

_INTERNAL_PATH = "/newsDetail_forward_"
_FONT_TAG = re.compile(r"</?font[^>]*>", re.IGNORECASE)


class _NextDataParser(HTMLParser):
    """Capture only the content of ``script#__NEXT_DATA__`` (type=application/json)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.captured: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if self.depth:
            self.depth += 1
            return
        if tag != "script":
            return
        values = {key.lower(): (value or "").strip() for key, value in attrs}
        if values.get("id") != "__NEXT_DATA__":
            return
        if values.get("type", "").lower() != "application/json":
            return
        self.depth = 1

    def handle_endtag(self, tag) -> None:
        if self.depth and tag == "script":
            self.depth = 0
        elif self.depth:
            self.depth -= 1

    def handle_data(self, data) -> None:
        if self.depth:
            self.captured.append(data)


class ThePaperProvider:
    platform = "thepaper"
    weights = THEPAPER_WEIGHTS
    absolute_floors = THEPAPER_ABSOLUTE_FLOORS

    def __init__(self, client: httpx.Client):
        self.client = client

    @staticmethod
    def _article_url(cont_id: str) -> str:
        return THEPAPER_ARTICLE_URL.format(cont_id=cont_id)

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(THEPAPER_HOT_URL)
        response.raise_for_status()
        raw = response.text
        try:
            items = self.parse_hot_list(raw, collected_at)
        except ProviderContractError as error:
            warning = _describe_schema(raw, error)
            return ProviderCapture(
                raw, ".json", (), metadata={"schema_warning": warning}
            )
        try:
            warning = _schema_warning(raw)
        except (TypeError, ValueError):
            warning = ""
        metadata = {"schema_warning": warning} if warning else {}
        return ProviderCapture(raw, ".json", items, metadata=metadata)

    def search(
        self,
        primary_keyword: str,
        page: int = 1,
        page_size: int = 15,
        collected_at: str = "",
    ) -> ProviderCapture:
        payload = {
            "word": primary_keyword,
            "orderType": 3,
            "pageNum": page,
            "pageSize": page_size,
            "searchType": 1,
        }
        response = self.client.post(
            THEPAPER_SEARCH_URL,
            json=payload,
            headers={"client-type": "1", "content-type": "application/json"},
        )
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".json", self.parse_search(raw, collected_at))

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        url = item.url or self._article_url(str(item.raw_payload.get("contId") or ""))
        try:
            response = self.client.get(url)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPError:
            html = ""
        content, parser = self._extract_content(html)
        validation = validate_full_text(
            content, item.title, item.summary, parser=parser
        )
        if validation.status != "accepted":
            reasons = ",".join(validation.reasons) or "empty"
            return ItemDetail(
                item.item_id, "", "rejected", item.publication_time,
                collected_at, item.url, f"rejected:{reasons}",
            )
        return ItemDetail(
            item.item_id, content, "full_text", item.publication_time,
            collected_at, item.url, "success",
        )

    def enrich_metrics(
        self,
        items: Sequence[HotItem],
        collected_at: str,
    ) -> tuple[HotItem, ...]:
        return tuple(items)

    @staticmethod
    def parse_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        return _parse_rows(raw, collected_at, _HOT_SELECT)

    @staticmethod
    def parse_search(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        return _parse_rows(raw, collected_at, _SEARCH_SELECT)

    @staticmethod
    def _extract_content(html: str) -> tuple[str, str]:
        structured = _extract_next_data_content(html)
        if structured:
            text = _html_to_paragraphs(structured)
            if validate_full_text(text, "", "", parser="next_data").status == "accepted":
                return text, "next_data"
        dom_text = extract_container_text(html, _ARTICLE_SELECTORS)
        if dom_text and validate_full_text(
            dom_text, "", "", parser="thepaper_dom"
        ).status == "accepted":
            return dom_text, "thepaper_dom"
        try:
            extracted = GeneralNewsExtractor().extract(html)
        except Exception:
            extracted = {}
        fallback = str(extracted.get("content") or "")
        return fallback, "gne"


def _HOT_SELECT(row: dict) -> bool:
    cont_type = row.get("contType")
    if not isinstance(cont_type, int) or cont_type != 0:
        return False
    if bool(row.get("paywalled")):
        return False
    url = str(row.get("url") or "")
    return _INTERNAL_PATH in url


def _SEARCH_SELECT(row: dict) -> bool:
    cont_type = row.get("contType")
    if not isinstance(cont_type, int) or cont_type != 0:
        return False
    if bool(row.get("paywalled")):
        return False
    url = str(row.get("url") or "")
    return _INTERNAL_PATH in url


def _parse_rows(
    raw: str,
    collected_at: str,
    selector,
) -> tuple[HotItem, ...]:
    if not raw or not raw.strip():
        raise ProviderContractError("thepaper response is empty")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderContractError("thepaper response is not valid JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    code = payload.get("code") if isinstance(payload, dict) else None
    if isinstance(data, dict) and code not in (None, 0, "0", 200, "200"):
        # Real envelope returned `code != 0`; the daily collection should
        # downgrade the platform to `partial` instead of marking it `failed`.
        return ()
    rows = _extract_rows(data)
    if rows is None:
        raise ProviderContractError("thepaper response has no row list")
    if not isinstance(rows, list):
        raise ProviderContractError(
            "thepaper hot list candidate is not a list: "
            f"type={type(rows).__name__}"
        )
    items: list[HotItem] = []
    for rank, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        if not selector(row):
            continue
        cont_id = str(row.get("contId") or "").strip()
        if not cont_id:
            continue
        title = _strip_font(str(row.get("name") or "").strip())
        if not title:
            continue
        summary_text = _strip_font(str(row.get("summary") or title).strip())
        interaction = number_or_none(row.get("interactionNum"))
        praise = number_or_none(row.get("praiseTimes"))
        metrics: dict[str, int] = {}
        if interaction is not None:
            metrics["interaction_num"] = interaction
        if praise is not None:
            metrics["praise_times"] = praise
        primary_value = interaction
        metric_name = "interaction_num"
        publication = _optional_publication(row.get("pubTimeLong"))
        url = str(row.get("url") or THEPAPER_ARTICLE_URL.format(cont_id=cont_id)).strip()
        items.append(
            HotItem(
                f"thepaper_{cont_id}",
                "thepaper",
                title,
                url,
                rank,
                HeatMetrics(
                    primary_value,
                    "" if primary_value is None else str(primary_value),
                    metric_name,
                    metrics,
                ),
                summary_text,
                publication,
                collected_at,
                row,
            )
        )
    return tuple(items)


_ROW_PATHS: tuple[tuple[str, ...], ...] = (
    ("hotNews", "contList"),
    ("hotNews",),
    ("hotList",),
    ("associateContList",),
    ("list",),
)


def _extract_rows(data: object) -> list | None:
    """Probe a small set of likely hot-list locations inside ``data``.

    The live `cache.thepaper.cn` endpoint has historically wrapped the hot
    rows under ``data.hotNews`` (list) but has also served them under
    ``data.hotNews.contList`` or ``data.associateContList``. We accept any of
    those shapes so that schema drift downgrades to an empty capture instead
    of raising.
    """
    if not isinstance(data, dict):
        return None
    for path in _ROW_PATHS:
        cursor: object = data
        for key in path:
            if not isinstance(cursor, dict):
                cursor = None
                break
            cursor = cursor.get(key)
        if cursor is None:
            continue
        if isinstance(cursor, list):
            return cursor
    return None


def _schema_warning(raw: str) -> str:
    """Return a short, non-secret description of any oddities in the envelope.

    Currently only reports ``code`` values that are not in the success set so
    the daily collection can surface a ``partial`` platform status with a
    human-readable reason, without revealing the underlying payload.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    code = payload.get("code")
    if code in (None, 0, "0", 200, "200"):
        return ""
    return f"thepaper envelope code={code}"


def _describe_schema(raw: str, error: Exception) -> str:
    base = _schema_warning(raw)
    return base or f"thepaper schema drift: {type(error).__name__}"


def _optional_publication(value: object) -> str | None:
    if value in (None, "", 0):
        return None
    try:
        millis = int(float(value))
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    seconds = millis / 1000.0 if millis > 10_000_000_000 else float(millis)
    try:
        parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_font(text: str) -> str:
    if not text:
        return text
    cleaned = _FONT_TAG.sub("", text)
    return " ".join(cleaned.split())


def _extract_next_data_content(html: str) -> str:
    parser = _NextDataParser()
    parser.feed(html)
    blob = "".join(parser.captured).strip()
    if not blob:
        return ""
    try:
        payload = json.loads(blob)
    except (TypeError, ValueError):
        return ""
    detail = (
        (((payload.get("props") or {}).get("pageProps") or {}).get("detailData") or {})
    )
    content_detail = detail.get("contentDetail") if isinstance(detail, dict) else None
    content = content_detail.get("content") if isinstance(content_detail, dict) else ""
    return str(content or "")


_ARTICLE_SELECTORS = (
    "#artibody",
    "#article-content",
    ".article-content",
    ".post_body",
    ".news_content",
    ".content-detail",
    "article",
)


def _html_to_paragraphs(html: str) -> str:
    if not html:
        return ""
    spaced = _BLOCK_RE.sub("\n", html)
    stripped = _TAG_RE.sub("", spaced)
    return "\n".join(part.strip() for part in stripped.split("\n") if part.strip())