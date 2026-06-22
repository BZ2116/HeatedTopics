import re
from urllib.parse import urlparse
from urllib.request import urlopen
from urllib.error import URLError

from src.hot_topic_types import SelectedTopic, TopicSource


def jina_reader_url(source_url: str) -> str:
    if source_url.startswith("http://") or source_url.startswith("https://"):
        return f"https://r.jina.ai/{source_url}"
    return f"https://s.jina.ai/{source_url}"


def read_url_text(url: str, timeout: int = 15) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_html(raw: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def try_read_direct(url: str, timeout: int = 15) -> str | None:
    try:
        raw = read_url_text(url, timeout=timeout)
        cleaned = clean_html(raw)
        if len(cleaned) >= 200:
            return cleaned
    except (URLError, TimeoutError, OSError):
        pass
    return None


def try_read_jina(url: str, timeout: int = 15) -> str | None:
    try:
        raw = read_url_text(jina_reader_url(url), timeout=timeout)
        cleaned = raw.strip()
        if len(cleaned) >= 200:
            return cleaned
    except (URLError, TimeoutError, OSError):
        pass
    return None


def enrich_topic(topic: SelectedTopic) -> TopicSource:
    tried_urls = []

    for url in topic.urls:
        if not url:
            continue
        tried_urls.append(url)

        text = try_read_direct(url)
        if text:
            return TopicSource(
                title=topic.title,
                source_url=url,
                content_preview=text,
                status="ok",
            )

        text = try_read_jina(url)
        if text:
            return TopicSource(
                title=topic.title,
                source_url=url,
                content_preview=text,
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