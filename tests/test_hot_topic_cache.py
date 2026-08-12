from heated_topics_v3.hot_topics.hot_topic_clustering import Topic
from heated_topics_v3.hot_topics.hot_topics_contracts import NormalizedHotItem
from heated_topics_v3.hot_topics.run_hot_topics import _brief_from_cache


def test_cached_brief_rebuilds_with_current_topic_metadata() -> None:
    item = NormalizedHotItem("1", "weibo", "费大厨塌房了", "费大厨塌房了", "https://x", 1, 1, "", "2026-08-12")
    topic = Topic("topic_001", "费大厨塌房了", (item,), ("weibo",), 1, 88.0)
    brief = _brief_from_cache(topic, {"summary": "缓存摘要", "key_facts": ["事实"], "evidence": []})
    assert brief.summary == "缓存摘要"
    assert brief.trend_score == 88.0
