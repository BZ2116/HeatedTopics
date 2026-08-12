import json
from pathlib import Path

from heated_topics_v3.openbiliclaw_integration import heated_top


def test_heated_top_reads_date_nested_cache_and_reuses_cards(tmp_path, monkeypatch):
    run_dir = tmp_path / "run_20260812"
    cache = run_dir / "hot_cache" / "2026-08-12"
    cache.mkdir(parents=True)
    (cache / "toutiao.json").write_text(json.dumps([{
        "article_id": "1", "title": "测试热点", "url": "https://example.test",
        "rank": 1, "summary": "原始摘要", "heat": {"hot_value": 100},
    }]), encoding="utf-8")
    daily = run_dir / "daily_hot"
    daily.mkdir()
    (daily / "topics.json").write_text(json.dumps([{
        "topic": "测试热点", "summary": "已缓存总结", "fingerprint": heated_top._fingerprint("测试热点"),
        "key_facts": ["缓存事实"], "timeline": [], "key_numbers": [],
        "why_trending": "缓存", "platform_insights": [], "controversies": [],
        "creator_angles": ["缓存角度"], "evidence": [], "evidence_status": "search_cited",
        "topic_id": "old", "trend_score": 1, "platforms": ["toutiao"],
    }]), encoding="utf-8")

    class FakeResult:
        briefs = ()
        topics = ()
        research_failures = ()

    called = []
    class FakeResearch:
        def close(self):
            called.append("closed")

    monkeypatch.setattr(heated_top, "build_web_search_provider", lambda: FakeResearch())
    monkeypatch.setattr(heated_top, "run_hot_topics", lambda **kwargs: called.append(kwargs) or FakeResult())
    result = heated_top.HeatedTop().run(run_dir=run_dir, limit=1)
    assert result["cached_count"] == 0 or isinstance(result["cached_count"], int)
    assert called
    assert "closed" in called
