from __future__ import annotations

import re
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
_BLOCK_TAGS = {
    "article",
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
}
_IGNORED_TAGS = {"script", "style", "nav", "footer"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


class _ContainerParser(HTMLParser):
    def __init__(self, selectors: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.selectors = selectors
        self.depth = 0
        self.ignored = 0
        self.parts: list[str] = []
        self.current: list[str] = []

    def _flush(self) -> None:
        paragraph = " ".join(self.current).strip()
        if paragraph:
            self.parts.append(paragraph)
        self.current.clear()

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        identity = {f"#{values.get('id', '')}"}
        identity.update(f".{value}" for value in values.get("class", "").split())
        if self.depth == 0 and identity.intersection(self.selectors):
            self.depth = 1
            return
        if not self.depth:
            return
        if self.ignored:
            if tag not in _VOID_TAGS:
                self.depth += 1
                self.ignored += 1
            return
        if tag in _IGNORED_TAGS:
            self.depth += 1
            self.ignored = 1
            return
        if tag in _BLOCK_TAGS or tag == "br":
            self._flush()
        if tag not in _VOID_TAGS:
            self.depth += 1

    def handle_endtag(self, tag) -> None:
        if not self.depth:
            return
        if self.ignored:
            self.ignored -= 1
            self.depth -= 1
            return
        if self.depth == 1:
            self._flush()
            self.depth = 0
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        self.depth -= 1

    def handle_startendtag(self, tag, attrs) -> None:
        if self.depth and not self.ignored and (tag in _BLOCK_TAGS or tag == "br"):
            self._flush()

    def handle_data(self, data) -> None:
        text = " ".join(data.split())
        if self.depth and not self.ignored and text:
            self.current.append(text)


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
    minimum_characters = (
        MIN_FALLBACK_ARTICLE_CHARACTERS
        if parser == "gne"
        else MIN_NATIVE_ARTICLE_CHARACTERS
    )
    references = tuple(
        sorted(
            {
                normalized
                for value in (title, summary)
                if (normalized := re.sub(r"\s+", "", value))
            },
            key=len,
            reverse=True,
        )
    )
    remainder = compact
    for reference in references:
        remainder = remainder.replace(reference, "")
    meaningful_remainder = re.sub(r"[\W_]+", "", remainder)
    if compact in references or (
        remainder != compact and len(meaningful_remainder) < minimum_characters
    ):
        reasons.append("title_or_summary")
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
