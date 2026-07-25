"""Authenticating provider for the zhihu.com official hot board.

The provider requires a local ``ZHIHU_COOKIE`` env value supplied by the user.
It never falls back to anonymous access and never proxies the credential to
any host outside the trust list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Literal, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from heated_topics_v3.contracts import (
    HeatMetrics,
    HotItem,
    ItemDetail,
    QualifiedArticle,
)
from heated_topics_v3.content import validate_full_text
from heated_topics_v3.heat import rank_platform_articles

from .common import (
    AuthenticationBlockedError,
    AuthenticationExpiredError,
    MissingCredentialError,
    ProviderCapture,
    ProviderContractError,
    number_or_none,
)


ZHIHU_COOKIE_ENV = "ZHIHU_COOKIE"
ZHIHU_HOT_API_URL = (
    "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"
    "?limit=50&desktop=true"
)
ZHIHU_HOT_PAGE_URL = "https://www.zhihu.com/hot"
ZHIHU_QUESTION_API_URL = (
    "https://www.zhihu.com/api/v4/questions/{question_id}"
    "?include=detail,answer_count,follower_count,visit_count,created,updated_time"
)
ZHIHU_ANSWERS_API_URL = (
    "https://www.zhihu.com/api/v4/questions/{question_id}/answers"
    "?include=data[*].content,voteup_count,comment_count,created_time,"
    "updated_time,author.name&limit=5&offset=0&platform=desktop&sort_by=default"
)
ZHIHU_QUESTION_PAGE_URL = "https://www.zhihu.com/question/{question_id}"
TRUSTED_ZHIHU_HOSTS = frozenset({"www.zhihu.com", "zhihu.com"})
TRANSIENT_STATUSES = frozenset({502, 503, 504})
MAX_REQUEST_ATTEMPTS = 2
MAX_HOT_ANSWERS = 5
_IGNORED_DETAIL_TAGS = {"script", "style", "nav", "footer", "button", "svg"}
_BLOCK_DETAIL_TAGS = {
    "p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "br",
}

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


@dataclass(frozen=True)
class _AnswerPayload:
    answer_id: str
    author: str
    content: str
    voteup_count: int
    comment_count: int
    created_at: str | None
    updated_at: str | None
    url: str
    favorite_count: int | None = None
    like_count: int | None = None

    def as_metadata(self) -> dict[str, object]:
        return {
            "answer_id": self.answer_id,
            "author": self.author,
            "voteup_count": self.voteup_count,
            "comment_count": self.comment_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "url": self.url,
            "favorite_count": self.favorite_count,
            "like_count": self.like_count,
        }


@dataclass(frozen=True)
class _QuestionPayload:
    question_text: str
    question_stats: Mapping[str, int | str]
    answers: tuple[_AnswerPayload, ...]
    publication_time: str | None


class _BlockTextParser(HTMLParser):
    """Block-aware text extractor for question/answer HTML fragments."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._capture_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_DETAIL_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in _BLOCK_DETAIL_TAGS:
            self._capture_depth += 1

    def handle_endtag(self, tag):
        if tag in _IGNORED_DETAIL_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag in _BLOCK_DETAIL_TAGS and self._capture_depth:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                self.parts.append("")

    def handle_data(self, data):
        if self._ignored_depth:
            return
        if not self._capture_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def _clean_html_blocks(value: str) -> tuple[str, ...]:
    parser = _BlockTextParser()
    parser.feed(value)
    return tuple(part.strip() for part in parser.parts if part.strip())


def _unix_iso(value: object) -> str | None:
    number = number_or_none(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()


def _question_id(item: HotItem) -> str:
    value = str(item.raw_payload.get("question_id") or "").strip()
    if not value.isdigit():
        raise ProviderContractError("zhihu question id missing")
    return value


def _parse_question_api(
    question_raw: str,
    answers_raw: str,
) -> _QuestionPayload:
    try:
        question = json.loads(question_raw)
        answers_envelope = json.loads(answers_raw)
    except (TypeError, ValueError) as error:
        raise ProviderContractError("zhihu question API returned invalid JSON") from error
    if not isinstance(question, dict) or not isinstance(answers_envelope, dict):
        raise ProviderContractError("zhihu question API envelope invalid")
    question_id = str(question.get("id") or "").strip()
    blocks = _clean_html_blocks(str(question.get("detail") or ""))
    if not question_id.isdigit() or not blocks:
        raise ProviderContractError("zhihu question API detail missing")
    rows = answers_envelope.get("data")
    if not isinstance(rows, list):
        raise ProviderContractError("zhihu answers API data missing")

    parsed_answers: list[_AnswerPayload] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        answer_id = str(row.get("id") or "").strip()
        content = "\n".join(_clean_html_blocks(str(row.get("content") or "")))
        if not answer_id.isdigit():
            continue
        validation = validate_full_text(
            content, "", "", parser="zhihu_answer"
        )
        if validation.status != "accepted":
            continue
        author = row.get("author") if isinstance(row.get("author"), dict) else {}
        parsed_answers.append(
            _AnswerPayload(
                answer_id=answer_id,
                author=str(author.get("name") or "匿名用户").strip() or "匿名用户",
                content=content,
                voteup_count=number_or_none(row.get("voteup_count")) or 0,
                comment_count=number_or_none(row.get("comment_count")) or 0,
                created_at=_unix_iso(row.get("created_time")),
                updated_at=_unix_iso(row.get("updated_time")),
                url=str(row.get("url") or (
                    f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
                )),
            )
        )
        if len(parsed_answers) == MAX_HOT_ANSWERS:
            break

    return _QuestionPayload(
        question_text="\n".join(blocks),
        question_stats={
            "question_id": question_id,
            "follower_count": number_or_none(question.get("follower_count")) or 0,
            "view_count": number_or_none(question.get("visit_count")) or 0,
            "answer_count": number_or_none(question.get("answer_count")) or 0,
        },
        answers=tuple(parsed_answers),
        publication_time=_unix_iso(question.get("created")),
    )


class _AnswerBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._capture_depth = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_DETAIL_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in _BLOCK_DETAIL_TAGS:
            self._capture_depth += 1

    def handle_endtag(self, tag):
        if tag in _IGNORED_DETAIL_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag in _BLOCK_DETAIL_TAGS and self._capture_depth:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                self.parts.append("")

    def handle_data(self, data):
        if self._ignored_depth or not self._capture_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


class _QuestionPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.question_blocks: list[str] = []
        self.answers: list[_AnswerPayload] = []
        self._q_root_open = False
        self._q_block_depth = 0
        self._q_ignored_depth = 0
        self._in_answer = False
        self._answer_id = ""
        self._author = ""
        self._answer_url = ""
        self._favorite: int | None = None
        self._like: int | None = None
        self._answer_text_parts: list[str] = []
        self._answer_text_depth = 0
        self._answer_text_ignored = 0
        self._answer_nested_div = False
        self._answer_href_pending = False
        self._button_label: str | None = None
        self._after_button: str | None = None
        self._last_a_classes: tuple[str, ...] = ()

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = tuple((attrs_dict.get("class") or "").split())
        if tag == "div" and "QuestionRichText" in classes:
            self._q_root_open = True
            self._q_block_depth = 0
            return
        if self._q_root_open and not self._q_ignored_depth:
            if tag in _IGNORED_DETAIL_TAGS:
                self._q_ignored_depth += 1
                return
            if tag in _BLOCK_DETAIL_TAGS:
                self._q_block_depth += 1
            return
        if self._q_root_open and self._q_ignored_depth:
            if tag in _IGNORED_DETAIL_TAGS:
                self._q_ignored_depth += 1
            return
        if tag == "article" and attrs_dict.get("data-answer-id"):
            self._in_answer = True
            self._answer_id = attrs_dict["data-answer-id"].strip()
            self._author = ""
            self._answer_url = ""
            self._favorite = None
            self._like = None
            self._answer_text_parts = []
            self._answer_text_depth = 0
            self._answer_text_ignored = 0
            self._after_button = None
            self._button_label = None
            return
        if self._in_answer:
            if tag == "div" and "RichContent-inner" in classes:
                self._answer_text_depth = 1
                self._answer_text_ignored = 0
                return
            if self._answer_text_depth and not self._answer_text_ignored:
                if tag == "div" or tag in _BLOCK_DETAIL_TAGS:
                    self._answer_text_depth += 1
                return
            if self._answer_text_depth and self._answer_text_ignored:
                return
            if tag == "button":
                self._button_label = ""
                return
            if tag == "a":
                self._last_a_classes = classes
                if "author" in classes:
                    self._after_button = "author"
                href = attrs_dict.get("href", "")
                if "/answer/" in href and not self._answer_url:
                    if href.startswith("/"):
                        self._answer_url = "https://www.zhihu.com" + href
                    else:
                        self._answer_url = href
                return
            if tag == "span" and self._after_button in {"favorite", "like"}:
                return

    def handle_endtag(self, tag):
        if self._q_root_open and self._q_ignored_depth:
            if tag in _IGNORED_DETAIL_TAGS:
                self._q_ignored_depth -= 1
            return
        if self._q_root_open:
            if tag == "div" and not self._q_ignored_depth:
                self._q_root_open = False
                return
            if not self._q_ignored_depth and tag in _BLOCK_DETAIL_TAGS and self._q_block_depth:
                self._q_block_depth -= 1
            return
        if not self._in_answer:
            return
        if tag == "article":
            self._flush_answer()
            self._in_answer = False
            return
        if self._answer_text_depth:
            if self._answer_text_ignored:
                if tag in _IGNORED_DETAIL_TAGS:
                    self._answer_text_ignored -= 1
                return
            if tag == "div" or tag in _BLOCK_DETAIL_TAGS:
                self._answer_text_depth -= 1
            return
        if tag == "button":
            label = self._button_label or ""
            if "收藏" in label:
                self._after_button = "favorite"
            elif "喜欢" in label:
                self._after_button = "like"
            else:
                self._after_button = None
            self._button_label = None
            return
        if tag == "a":
            if self._after_button == "author" and self._author == "":
                pass
            self._after_button = None
            return
        if tag == "span" and self._after_button in {"favorite", "like"}:
            self._after_button = None

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if (
            self._q_root_open
            and not self._q_ignored_depth
            and self._q_block_depth
        ):
            self.question_blocks.append(text)
            return
        if not self._in_answer:
            return
        if (
            self._answer_text_depth
            and not self._answer_text_ignored
        ):
            self._answer_text_parts.append(text)
            return
        if self._button_label is not None:
            self._button_label += text
            return
        if self._after_button == "author" and self._author == "":
            self._author = text
            self._after_button = None
            return
        if self._after_button in {"favorite", "like"} and text.isdigit():
            value = int(text)
            if self._after_button == "favorite":
                self._favorite = value
            else:
                self._like = value
            self._after_button = None

    def _flush_answer(self):
        if not self._answer_id:
            return
        text = "\n".join(
            part.strip() for part in self._answer_text_parts if part.strip()
        )
        validation = validate_full_text(text, "", "", parser="zhihu_answer")
        if validation.status != "accepted":
            return
        self.answers.append(
            _AnswerPayload(
                answer_id=self._answer_id,
                author=self._author or "匿名用户",
                content=text,
                voteup_count=0,
                comment_count=0,
                created_at=None,
                updated_at=None,
                url=self._answer_url,
                favorite_count=self._favorite,
                like_count=self._like,
            )
        )


def _parse_question_html(raw: str, question_id: str) -> _QuestionPayload:
    parser = _QuestionPageParser()
    parser.feed(raw)
    if not parser.question_blocks:
        raise ProviderContractError("zhihu question HTML detail missing")
    return _QuestionPayload(
        question_text="\n".join(part for part in parser.question_blocks if part).strip(),
        question_stats={
            "question_id": question_id,
            "follower_count": 0,
            "view_count": 0,
            "answer_count": len(parser.answers),
        },
        answers=tuple(parser.answers),
        publication_time=None,
    )


def _render_question_detail(payload: _QuestionPayload) -> str:
    sections = ["问题描述", payload.question_text]
    for index, answer in enumerate(payload.answers, 1):
        sections.extend(
            [
                f"热门回答 {index}",
                f"作者：{answer.author}",
                f"赞同：{answer.voteup_count}",
                f"评论：{answer.comment_count}",
                answer.content,
            ]
        )
    return "\n\n".join(section for section in sections if section.strip())


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
        question_id = _question_id(item)
        try:
            question = self._get(ZHIHU_QUESTION_API_URL.format(question_id=question_id))
            answers = self._get(ZHIHU_ANSWERS_API_URL.format(question_id=question_id))
            payload = _parse_question_api(question.text, answers.text)
            fetch_status = "success" if payload.answers else "partial:no_answers"
        except ProviderContractError:
            page = self._get(
                ZHIHU_QUESTION_PAGE_URL.format(question_id=question_id)
            )
            payload = _parse_question_html(page.text, question_id)
            fetch_status = (
                "success:html_fallback"
                if payload.answers
                else "partial:html_fallback:no_answers"
            )

        content = _render_question_detail(payload)
        validation = validate_full_text(
            content, item.title, item.summary, parser="zhihu_question"
        )
        if validation.status != "accepted":
            return ItemDetail(
                item_id=item.item_id,
                content="",
                content_status="rejected",
                publication_time=payload.publication_time,
                collected_at=collected_at,
                source_url=item.url,
                fetch_status="rejected:" + ",".join(validation.reasons),
            )
        return ItemDetail(
            item_id=item.item_id,
            content=content,
            content_status="full_text",
            publication_time=payload.publication_time,
            collected_at=collected_at,
            source_url=item.url,
            fetch_status=fetch_status,
            metadata={
                "question": dict(payload.question_stats),
                "answers": [answer.as_metadata() for answer in payload.answers],
            },
        )

    def rank_articles(
        self, articles: Sequence[QualifiedArticle]
    ) -> tuple[QualifiedArticle, ...]:
        ordered = list(rank_platform_articles(tuple(articles), self.weights))
        ordered.sort(key=lambda article: article.hot_item.item_id)
        ordered.sort(
            key=lambda article: float(
                article.detail.metadata.get("question", {}).get(
                    "view_count", 0
                )
            ),
            reverse=True,
        )
        ordered.sort(
            key=lambda article: article.hot_item.rank or 10**9
        )
        ordered.sort(
            key=lambda article: float(article.hot_item.heat.value or 0),
            reverse=True,
        )
        return tuple(ordered)

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
