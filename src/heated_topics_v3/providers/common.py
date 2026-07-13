"""Contracts shared by platform providers."""
from dataclasses import dataclass
from html.parser import HTMLParser

from heated_topics_v3.contracts import HotItem


class ProviderContractError(ValueError):
    """Raised when a public endpoint response does not match its success contract."""


@dataclass(frozen=True)
class ProviderCapture:
    raw_text: str
    raw_suffix: str
    items: tuple[HotItem, ...]


def number_or_none(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs) -> None:
        if self.depth and tag in {"script", "style"}:
            self.ignored += 1
        elif tag == "article":
            self.depth = 1
        elif self.depth:
            self.depth += 1

    def handle_endtag(self, tag) -> None:
        if self.ignored:
            if tag in {"script", "style"}:
                self.ignored -= 1
        elif self.depth:
            self.depth -= 1

    def handle_data(self, data) -> None:
        if self.depth and not self.ignored and data.strip():
            self.parts.append(data.strip())


def article_text(html: str) -> str:
    parser = _ArticleParser()
    parser.feed(html)
    return "\n".join(parser.parts)
