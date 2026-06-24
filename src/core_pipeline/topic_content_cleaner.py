import re
from dataclasses import dataclass


PAGE_CHROME_LINES = {
    "NEW",
    "搜索结果",
    "综合",
    "智搜",
    "实时",
    "用户",
    "视频",
    "图片",
    "话题",
    "高级搜索",
    "热门",
    "登录",
    "关注",
    "广告",
    "展开c",
    "下一页",
    "百度热搜",
    "刷新",
    "我的",
}

SIDEBAR_PATTERNS = [
    re.compile(r"^\d+\s+.+"),
    re.compile(r"^热搜指数[:：]?\d*"),
    re.compile(r"^查看更多"),
    re.compile(r"^Copyright\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class CleanedContent:
    raw_content_preview: str
    clean_content: str
    removed_line_count: int
    content_quality: str


def clean_topic_content(
    title: str,
    raw_text: str,
    max_clean_chars: int = 800,
    max_raw_preview_chars: int = 500,
) -> CleanedContent:
    raw = str(raw_text or "")
    raw_preview = _truncate(_collapse_spaces(raw), max_raw_preview_chars)
    if not raw.strip():
        fallback = str(title).strip()
        return CleanedContent(
            raw_content_preview="",
            clean_content=fallback,
            removed_line_count=0,
            content_quality="fallback",
        )
    title_terms = _title_terms(title)
    lines = [_clean_line(line) for line in raw.splitlines()]
    kept: list[str] = []
    removed = 0
    sidebar_mode = False
    for line in lines:
        if not line:
            continue
        if _is_page_chrome(line):
            removed += 1
            if line == "百度热搜":
                sidebar_mode = True
            continue
        if sidebar_mode and not _line_matches_title(line, title_terms):
            removed += 1
            continue
        if _is_sidebar_line(line) and not _line_matches_title(line, title_terms):
            removed += 1
            continue
        kept.append(line)
    clean = _truncate(_collapse_spaces("\n".join(_dedupe_adjacent(kept))), max_clean_chars)
    if not clean:
        clean = str(title).strip()
        quality = "fallback"
    elif removed:
        quality = "partial"
    else:
        quality = "clean"
    return CleanedContent(
        raw_content_preview=raw_preview,
        clean_content=clean,
        removed_line_count=removed,
        content_quality=quality,
    )


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _dedupe_adjacent(lines: list[str]) -> list[str]:
    result: list[str] = []
    previous = None
    for line in lines:
        if line == previous:
            continue
        result.append(line)
        previous = line
    return result


def _is_page_chrome(line: str) -> bool:
    return line in PAGE_CHROME_LINES or line.lower() in {"c", "new"}


def _is_sidebar_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in SIDEBAR_PATTERNS)


def _title_terms(title: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9一-鿿]{2,}", str(title))
    return [term.lower() for term in terms]


def _line_matches_title(line: str, title_terms: list[str]) -> bool:
    normalized = line.lower()
    return any(term and term in normalized for term in title_terms)