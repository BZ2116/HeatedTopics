import re
from dataclasses import replace

from src.search_discovery.types import CreatorProfile, SearchResult


DOMESTIC_PROFILE_TYPES = {
    "general_hot_topic_creator",
    "business_startup_creator",
    "domestic_hot_topic_creator",
}

GENERIC_TOPIC_TITLES = {
    "财经",
    "股票",
    "股市",
    "股市评论",
    "A股",
    "A股动态",
    "新闻",
    "热点",
    "行业动态",
}

CHANNEL_TITLE_TERMS = [
    "客户端",
    "频道",
    "首页",
    "官网",
    "官方网站",
    "资讯网站",
    "权威的证券财经资讯网站",
]

CONCRETE_EVENT_TERMS = [
    "回应",
    "通报",
    "发布",
    "落地",
    "首日",
    "新规",
    "调整",
    "变化",
    "上涨",
    "下跌",
    "涨停",
    "成交",
    "放量",
    "融资",
    "裁员",
    "事故",
    "监管",
    "政策",
    "中报",
]

SOURCE_OR_META_TERMS = {
    "专题",
    "证监会网站",
    "证券时报",
    "每日经济新闻",
    "中国基金报",
    "东方财富Choice数据",
    "央视新闻",
    "财联社",
    "中国证券报",
    "上海证券报",
    "券商中国",
    "第一财经",
}


def is_usable_topic_result(profile: CreatorProfile, result: SearchResult) -> bool:
    return topic_result_candidate(profile, result) is not None


def topic_result_candidate(profile: CreatorProfile, result: SearchResult) -> SearchResult | None:
    if not _uses_domestic_topic_quality(profile):
        return result

    title = result.title.strip()
    if not title:
        return None

    if not _has_chinese_signal(f"{title} {result.snippet}"):
        return None

    if _is_exact_profile_keyword(title, profile) or title in GENERIC_TOPIC_TITLES:
        return _repair_from_snippet(result)

    if title in GENERIC_TOPIC_TITLES:
        return _repair_from_snippet(result)

    if _looks_like_channel_or_product_title(title) and not _has_concrete_event_signal(title):
        return _repair_from_snippet(result)

    if _looks_like_category_url(result.url) and not _has_concrete_event_signal(title):
        return _repair_from_snippet(result)

    return result


def _uses_domestic_topic_quality(profile: CreatorProfile) -> bool:
    if profile.profile_type in DOMESTIC_PROFILE_TYPES:
        return True
    text = " ".join([profile.role, *profile.track_tags, *profile.custom_keywords])
    return any(term in text for term in ["国内", "热点", "财经", "A股", "股票"])


def _is_exact_profile_keyword(title: str, profile: CreatorProfile) -> bool:
    normalized_title = _normalize_title(title)
    return normalized_title in {_normalize_title(keyword) for keyword in profile.all_keywords()}


def _looks_like_channel_or_product_title(title: str) -> bool:
    return any(term in title for term in CHANNEL_TITLE_TERMS) or "_" in title or " - " in title


def _looks_like_category_url(url: str) -> bool:
    lowered = url.lower()
    category_markers = [
        "/channel/",
        "channel=",
        "/list",
        "/news/gushi/",
        "stock.eastmoney.com",
        "emwap.eastmoney.com",
        "wap.eastmoney.com",
        "guba.sina.cn/list",
    ]
    return any(marker in lowered for marker in category_markers)


def _has_concrete_event_signal(title: str) -> bool:
    if any(term in title for term in CONCRETE_EVENT_TERMS):
        return True
    return any(char.isdigit() for char in title)


def _repair_from_snippet(result: SearchResult) -> SearchResult | None:
    repaired_title = _specific_title_from_snippet(result.snippet)
    if not repaired_title:
        return None
    return replace(result, title=repaired_title)


def _specific_title_from_snippet(snippet: str) -> str:
    tokens = _snippet_tokens(snippet)
    for index, token in enumerate(tokens):
        if not _is_specific_topic_token(token):
            continue
        parts = [token]
        for next_token in tokens[index + 1 : index + 4]:
            if _is_meta_token(next_token):
                break
            if len(" ".join(parts)) + len(next_token) > 58:
                break
            parts.append(next_token)
            if next_token.endswith(("?", "？")):
                break
        candidate = " ".join(parts).strip()
        if 8 <= len(candidate) <= 60:
            return candidate
    return ""


def _snippet_tokens(snippet: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", snippet.strip())
    cleaned = re.sub(r"(\d+读|阅读量?\d+|昨天\d{1,2}:\d{2}|\d{2}-\d{2}|\d{4}-\d{2}-\d{2})", " ", cleaned)
    return [token.strip(" ，。；;|") for token in cleaned.split(" ") if token.strip(" ，。；;|")]


def _is_specific_topic_token(token: str) -> bool:
    if _is_meta_token(token):
        return False
    if not _has_chinese_signal(token):
        return False
    if _normalize_title(token) in {_normalize_title(value) for value in GENERIC_TOPIC_TITLES}:
        return False
    return _has_concrete_event_signal(token) or any(marker in token for marker in ["发生了什么", "有何影响", "什么信号"])


def _is_meta_token(token: str) -> bool:
    if token in SOURCE_OR_META_TERMS:
        return True
    if token.endswith(("报", "网", "新闻", "数据")) and len(token) <= 10:
        return True
    return bool(re.fullmatch(r"\d+|\d{1,2}:\d{2}|昨天|今天|分钟前|小时前", token))


def _has_chinese_signal(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _normalize_title(value: str) -> str:
    return value.strip().lower().replace(" ", "")
