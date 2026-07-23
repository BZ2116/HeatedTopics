from __future__ import annotations

import re
from dataclasses import replace
from html.parser import HTMLParser

from .contracts import ContentValidation


MIN_NATIVE_ARTICLE_CHARACTERS = 80
MIN_FALLBACK_ARTICLE_CHARACTERS = 200
_CHROME = (
    "登录",
    "发表评论",
    "推荐阅读",
    "相关阅读",
    "返回首页",
    "打开客户端",
    "扫码下载",
    "版权声明",
)


class _ContainerParser(HTMLParser):
    def __init__(self, selectors: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.selectors = selectors
        self.depth = 0
        self.ignored = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        identity = {f"#{values.get('id', '')}"}
        identity.update(f".{value}" for value in values.get("class", "").split())
        if self.depth == 0 and identity.intersection(self.selectors):
            self.depth = 1
            return
        if self.depth and tag in {"script", "style", "nav", "footer"}:
            self.ignored += 1
        elif self.depth:
            self.depth += 1

    def handle_endtag(self, tag) -> None:
        if self.ignored:
            if tag in {"script", "style", "nav", "footer"}:
                self.ignored -= 1
        elif self.depth:
            self.depth -= 1

    def handle_data(self, data) -> None:
        text = " ".join(data.split())
        if self.depth and not self.ignored and text:
            self.parts.append(text)


def extract_container_text(html: str, selectors: tuple[str, ...]) -> str:
    parser = _ContainerParser(selectors)
    parser.feed(html)
    return "\n".join(parser.parts)


def validate_full_text(
    content: str,
    title: str,
    summary: str,
    *,
    parser: str = "",
) -> ContentValidation:
    cleaned = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    compact = re.sub(r"\s+", "", cleaned)
    paragraphs = tuple(part for part in re.split(r"\n+", cleaned) if part)
    reasons: list[str] = []
    if compact in {re.sub(r"\s+", "", title), re.sub(r"\s+", "", summary)}:
        reasons.append("title_or_summary")
    minimum_characters = (
        MIN_FALLBACK_ARTICLE_CHARACTERS
        if parser == "gne"
        else MIN_NATIVE_ARTICLE_CHARACTERS
    )
    if len(compact) < minimum_characters:
        reasons.append("too_short")
    sentence_count = len(re.findall(r"[。！？!?]", cleaned))
    if len(paragraphs) < 2 and sentence_count < 3:
        reasons.append("insufficient_structure")
    chrome_hits = sum(cleaned.count(value) for value in _CHROME)
    if chrome_hits >= 4:
        reasons.append("page_chrome")
    status = "rejected" if reasons else "accepted"
    return ContentValidation(
        status=status,
        parser=parser,
        character_count=len(compact),
        paragraph_count=len(paragraphs),
        reasons=tuple(reasons),
    )


def with_parser(result: ContentValidation, parser: str) -> ContentValidation:
    return replace(result, parser=parser)
