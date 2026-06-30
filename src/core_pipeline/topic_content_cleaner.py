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
    "弹幕互动",
    "刚刚",
    "播放视频",
    "千问",
    "智搜回答",
}

SIDEBAR_PATTERNS = [
    re.compile(r"^\d+$"),
    re.compile(r"^\d+\s+.+"),
    re.compile(r"^热搜指数[:：]?\d*"),
    re.compile(r"^查看更多"),
    re.compile(r"^Copyright\b", re.IGNORECASE),
    re.compile(r"^[\ue000-\uf8ff\s]+$"),
    re.compile(r"^https?://\S+$", re.IGNORECASE),
]

STRONG_SIDEBAR_PATTERNS = [
    re.compile(r"^热搜榜第\d+名$"),
    re.compile(r"^百度热搜\s+新闻\s+hao123\b.*"),
]

METADATA_PATTERNS = [
    re.compile(r"^(今天|昨天)?\d{1,2}:\d{2}(\s+来自\s+.+)?$"),
    re.compile(r"^(刚刚|\d+分钟前|今天|昨天|\d{1,2}月\d{1,2}日).*\s来自\s+.+"),
    re.compile(r"^(广告|自主创作)\s+.*\s来自\s+.+"),
    re.compile(r"^\d+分钟前\s+深度思考.*AI生成\)?$"),
]

PROMOTIONAL_PATTERNS = [
    re.compile(r"^【?AI志愿"),
    re.compile(r"高考志愿Agent"),
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
    skip_ad_content_lines = 0
    for index, line in enumerate(lines):
        if not line:
            continue
        if skip_ad_content_lines > 0:
            removed += 1
            skip_ad_content_lines -= 1
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _is_page_chrome(line):
            removed += 1
            if line == "百度热搜":
                sidebar_mode = True
            continue
        if _is_ad_metadata_line(line):
            removed += 1
            skip_ad_content_lines = 2
            continue
        if _is_promotional_line(line):
            removed += 1
            continue
        if _is_article_title_chrome(line, title_terms):
            removed += 1
            continue
        if _is_metadata_line(line) or _is_source_account_line(line, next_line):
            removed += 1
            continue
        if _is_strong_sidebar_line(line):
            removed += 1
            continue
        if sidebar_mode and not _line_matches_title(line, title_terms):
            removed += 1
            continue
        if _is_sidebar_line(line) and not _line_matches_title(line, title_terms):
            removed += 1
            continue
        stripped_line = _strip_inline_chrome(line)
        if not stripped_line:
            removed += 1
            continue
        line = stripped_line
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


def _is_strong_sidebar_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in STRONG_SIDEBAR_PATTERNS)


def _is_metadata_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in METADATA_PATTERNS)


def _is_ad_metadata_line(line: str) -> bool:
    return line.startswith("广告 ") and " 来自 " in line


def _is_promotional_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in PROMOTIONAL_PATTERNS)


def _is_article_title_chrome(line: str, title_terms: list[str]) -> bool:
    if len(line) > 120:
        return False
    if _line_matches_title(line, title_terms):
        return bool(re.search(r"[-_](新华网|中国新闻网|央视网|人民网)$", line))
    return bool(re.search(r"^[^-_]{4,100}[-_](新华网|中国新闻网|央视网|人民网)$", line))


def _is_source_account_line(line: str, next_line: str) -> bool:
    if not _is_metadata_line(next_line):
        return False
    if len(line) > 20:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9一-鿿_\-·]+", line))


def _strip_inline_chrome(line: str) -> str:
    cleaned = re.sub(r"[\ue000-\uf8ff]", " ", line)
    cleaned = re.sub(r"https?://\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Title:\s*", "", cleaned, flags=re.IGNORECASE)
    if re.fullmatch(r"URL:\s*", cleaned, flags=re.IGNORECASE):
        return ""
    cleaned = re.sub(r"\s*您需要先启用javascript功能\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("换一换", " ")
    cleaned = re.sub(r"\s*百度热搜\s+新闻\s+hao123\b.*$", " ", cleaned)
    cleaned = re.sub(r"\s*热搜榜\s+更多\s+\d+\s+.*$", " ", cleaned)
    cleaned = re.sub(r"(\s+\d+\s+\S{2,30}){3,}.*$", " ", cleaned)
    cleaned = re.sub(r"\s*百度首页\s+登录.*?(?=(刚刚|今天|昨天|\d{4}年|\d{1,2}月\d{1,2}日|$))", " ", cleaned)
    cleaned = re.sub(r"\s*更新至\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}\s+发表.*$", " ", cleaned)
    cleaned = re.sub(r"\s*\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}\s+发表\s*$", " ", cleaned)
    cleaned = re.sub(r"\s*展开c\s*$", " ", cleaned)
    cleaned = _strip_news_article_template(cleaned)
    return _clean_line(cleaned)


def _strip_news_article_template(line: str) -> str:
    cleaned = re.sub(r"\s*阅读下一篇[:：].*$", " ", line)
    cleaned = re.sub(r"\s*【责任编辑[:：][^】]*】.*$", " ", cleaned)
    cleaned = re.sub(r"\s*【纠错】\s*", " ", cleaned)
    cleaned = re.sub(r"\s*字体[:：]\s*小\s+中\s+大\s+分享到[:：]?\s*", " ", cleaned)
    cleaned = re.sub(r"\s*分享到[:：]?\s*", " ", cleaned)
    if "新华社" in cleaned and "新华网" in cleaned and "来源：新华网" in cleaned:
        cleaned = re.sub(r"^.*?(新华社[^，。；：\s]{0,24}电)", r"\1", cleaned)
    return cleaned


def _title_terms(title: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9一-鿿]{2,}", str(title))
    return [term.lower() for term in terms]


def _line_matches_title(line: str, title_terms: list[str]) -> bool:
    normalized = line.lower()
    return any(term and term in normalized for term in title_terms)
