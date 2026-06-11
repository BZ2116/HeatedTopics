from collections import defaultdict

from src.hot_topic_types import HotRecord, SelectedTopic


IMPORTANT_KEYWORDS = [
    "ai",
    "人工智能",
    "大模型",
    "科技",
    "芯片",
    "商业",
    "融资",
    "公司",
    "安全",
    "网安",
    "教育",
]


def normalize_title_key(title: str) -> str:
    return "".join(title.lower().split())


def keyword_bonus(title: str) -> int:
    lowered = title.lower()
    return sum(5 for keyword in IMPORTANT_KEYWORDS if keyword in lowered)


def select_topics(
    records: list[HotRecord],
    min_count: int = 5,
    max_count: int = 8,
) -> list[SelectedTopic]:
    grouped: dict[str, list[HotRecord]] = defaultdict(list)
    titles: dict[str, str] = {}

    for item in records:
        key = normalize_title_key(item.title)
        grouped[key].append(item)
        titles.setdefault(key, item.title)

    selected: list[SelectedTopic] = []
    for key, items in grouped.items():
        sorted_items = sorted(items, key=lambda item: item.rank)
        platforms = []
        ranks = {}
        urls = []

        for item in sorted_items:
            if item.platform not in platforms:
                platforms.append(item.platform)
                ranks[item.platform] = item.rank
            if item.url and item.url not in urls:
                urls.append(item.url)

        best_rank = min(item.rank for item in items)
        cross_platform_bonus = 30 * (len(platforms) - 1)
        rank_score = max(0, 20 - best_rank)
        score = cross_platform_bonus + rank_score + keyword_bonus(titles[key])

        selected.append(
            SelectedTopic(
                title=titles[key],
                platforms=platforms,
                ranks=ranks,
                urls=urls,
                score=score,
            )
        )

    selected.sort(key=lambda item: item.score, reverse=True)
    return selected[:max_count]