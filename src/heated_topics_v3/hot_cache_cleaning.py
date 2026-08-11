"""Platform-specific cleanup for hot-cache article bodies."""

from __future__ import annotations

import re
from typing import Any, Callable


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _sina(lines: list[str], _: str) -> tuple[list[str], str]:
    for index, line in enumerate(lines):
        if line.startswith("缩小字体 放大字体"):
            lines = lines[index + 1:]
            break
    if lines and lines[0] in {"腾讯QQ QQ空间", "微信", "微博"}:
        lines.pop(0)
    for index, line in enumerate(lines):
        if line.startswith(("关键词 :", "更多彩票资讯", "相关阅读", "推荐阅读", "大家都在看", "赛博对话", "热搜时代", "点击进入专题：")):
            lines = lines[:index]
            break
    lines = [line for line in lines if not line.startswith("责任编辑：")]
    source = lines.pop().removeprefix("来源：").strip() if lines and lines[-1].startswith("来源：") else ""
    return lines, source


def _toutiao(lines: list[str], _: str) -> tuple[list[str], str]:
    if lines and lines[0] == "事件详情":
        lines = lines[1:lines.index("相关内容") if "相关内容" in lines else len(lines)]
        if lines and re.fullmatch(r"\d{2}:\d{2}", lines[0]):
            lines.pop(0)
        source_like = lambda value: bool(re.search(r"评论|小时前|昨天|分钟前|天前", value))
        if lines and not source_like(lines[0]):
            lines.pop(0)
        if lines and source_like(lines[0]):
            lines.pop(0)
    for index, line in enumerate(lines):
        if line.startswith(("编辑：", "实习编辑：", "责任编辑：", "【来源：", "声明：", "本文来源：")):
            lines = lines[:index]
            break
    while lines and re.match(r"^(策划|统筹|制作)[：:]", lines[-1]):
        lines.pop()
    return lines, ""


def _netease(lines: list[str], _: str) -> tuple[list[str], str]:
    source = lines.pop(0).removeprefix("来源：").strip() if lines and lines[0].startswith("来源：") else ""
    for index, line in enumerate(lines):
        if line.startswith(("编辑", "校对", "每日经济新闻综合", "特别声明：", "Notice:")):
            lines = lines[:index]
            break
    while lines and (lines[-1].startswith("来源：") or lines[-1].startswith("本文来源：") or lines[-1].startswith("（来源：") or lines[-1].startswith("来源 |")):
        line = lines.pop()
        source = source or re.sub(r"^[（(]?本文?来源[：:|]\s*|^[（(]?来源[：:|]\s*", "", line).rstrip("）)").strip()
    lines = [line for line in lines if not re.fullmatch(r"\d+", line)]
    while lines and re.fullmatch(r"[（(](总台记者|记者).*[）)]", lines[-1]):
        lines.pop()
    return lines, source


def _juejin(lines: list[str], title: str) -> tuple[list[str], str]:
    if lines and lines[0] == title:
        lines.pop(0)
    if lines and len(lines) > 1 and re.fullmatch(r"[\w\u4e00-\u9fff_-]+", lines[0]):
        lines.pop(0)
    while lines and (re.fullmatch(r"\d{4}-\d{2}-\d{2}", lines[0]) or re.fullmatch(r"\d+", lines[0]) or lines[0].startswith("阅读")):
        lines.pop(0)
    for index, line in enumerate(lines):
        if line == "阅读" and ("粉丝" in lines[index + 1:index + 4] or "目录" in lines[index + 1:index + 5]):
            lines = lines[:index]
            break
    if len(lines) >= 2 and lines[-2:] == ["目录", "收起"]:
        lines = lines[:-2]
    for index in range(max(0, len(lines) - 6), len(lines)):
        if lines[index] == "文章" and index + 1 < len(lines) and re.fullmatch(r"[\d.]+[kKmMwW]?", lines[index + 1]):
            start = index - 4 if index >= 3 and "@" in lines[index - 3] else index - 2
            lines = lines[:max(0, start)]
            break
    return lines, ""


def _zhihu_daily(lines: list[str], _: str) -> tuple[list[str], str]:
    if lines and "查看知乎原文" in lines[0]:
        lines.pop(0)
    if lines and lines[-1] == "查看知乎讨论":
        lines.pop()
    return lines, ""


_CLEANERS: dict[str, Callable[[list[str], str], tuple[list[str], str]]] = {
    "sina_news": _sina, "toutiao": _toutiao, "netease_news": _netease,
    "juejin": _juejin, "zhihu_daily": _zhihu_daily,
}


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose body fields are normalized for its platform."""
    result = dict(record)
    raw = str(record.get("body_text") or "")
    cleaner = _CLEANERS.get(str(record.get("platform") or ""))
    lines, source = cleaner(_lines(raw), str(record.get("title") or "")) if cleaner else (_lines(raw), "")
    body = "\n".join(lines).strip()
    count = len(re.sub(r"\s+", "", body))
    result.update(body_text_raw=raw, body_text=body, body_clean_char_count=count, body_clean_status="accepted" if count >= 80 else ("empty_body" if not body else "too_short"))
    if source:
        result["body_source"] = source
    return result


def clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [clean_record(record) for record in records]
