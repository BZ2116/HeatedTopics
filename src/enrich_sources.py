from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import URLError

from src.hot_topic_types import SelectedTopic, TopicSource


def jina_reader_url(source_url: str) -> str:
    if source_url.startswith("http://") or source_url.startswith("https://"):
        return f"https://r.jina.ai/{source_url}"
    return f"https://s.jina.ai/{quote(source_url)}"


def read_url_text(url: str, timeout: int = 15) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def enrich_topic(topic: SelectedTopic, max_chars: int = 3000) -> TopicSource:
    for url in topic.urls:
        target = url or topic.title
        try:
            text = read_url_text(jina_reader_url(target))
        except (URLError, TimeoutError, OSError):
            continue
        cleaned = text.strip()
        if len(cleaned) >= 120:
            return TopicSource(
                title=topic.title,
                source_url=target,
                content_preview=cleaned[:max_chars],
                status="ok",
            )

    return TopicSource(
        title=topic.title,
        source_url=topic.urls[0] if topic.urls else "",
        content_preview="未能稳定读取详情页，Demo 阶段基于热榜标题、平台和排名生成低置信度卡片。",
        status="fallback",
    )


def enrich_topics(topics: list[SelectedTopic]) -> list[TopicSource]:
    return [enrich_topic(topic) for topic in topics]