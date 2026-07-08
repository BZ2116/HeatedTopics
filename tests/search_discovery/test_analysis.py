from pathlib import Path

from src.search_discovery.analysis import build_topic_analysis
from src.search_discovery.types import CandidateTopic, EnrichedContent, SearchResult


def _topic(**overrides):
    base = {
        "topic_id": "search_topic_001",
        "title": "AI Agent 工具链",
        "matched_keywords": ["AI Agent", "MCP"],
        "keyword_categories": ["tech_project"],
        "profile_match_score": 80,
        "freshness": "breaking",
        "detail_level": "high",
        "risk_level": "low",
        "source_hits": [
            {
                "source_id": "github_search",
                "title": "agent/repo",
                "url": "https://github.com/agent/repo",
                "content_type": "repo",
                "source_weight": 100,
                "metrics": {"stars": 1200, "recently_recommended": True},
                "recently_recommended": True,
            },
            {
                "source_id": "baidu_qianfan_search",
                "title": "AI Agent 分析",
                "url": "https://example.com/agent",
                "content_type": "web",
                "source_weight": 70,
                "metrics": {},
                "recently_recommended": False,
            },
        ],
        "summary": "AI Agent 工具链在开源项目和中文资料中持续升温。",
        "open_questions": [],
        "created_at": "2026-06-30T10:00:00+08:00",
        "verification_score": 82,
        "evidence_level": "strong",
        "verification_notes": ["多个独立来源指向同一话题，基础可信度较高。"],
        "risk_flags": [],
        "topic_score": 73,
    }
    base.update(overrides)
    return CandidateTopic(**base)


def _result(result_id, source_id, title, content_type="web", risk="ok"):
    return SearchResult(
        result_id=result_id,
        source_id=source_id,
        source_role="primary_search",
        query="AI Agent MCP",
        keyword_category="tech_project",
        title=title,
        url=f"https://example.com/{result_id}",
        snippet=f"{title} 摘要",
        content_type=content_type,
        fetch_status=risk,
        metrics={"recently_recommended": result_id.endswith("1")},
        matched_keywords=["AI Agent"],
    )


def test_build_topic_analysis_counts_statistics_and_topic_features():
    topics = [_topic()]
    results = [
        _result("r1", "github_search", "agent/repo", content_type="repo"),
        _result("r2", "baidu_qianfan_search", "AI Agent 分析", content_type="web"),
    ]
    evidence = [
        EnrichedContent(result_id="r1", url="https://github.com/agent/repo", title="agent/repo", content="开源项目证据", published_at="2026-06-30T09:00:00+08:00", content_quality="high", evidence_confidence="high"),
        EnrichedContent(result_id="r2", url="https://example.com/agent", title="AI Agent 分析", content="中文资料证据", published_at="2026-06-30T09:30:00+08:00", content_quality="medium", evidence_confidence="medium"),
    ]

    analysis = build_topic_analysis(
        profile_path=Path("config/search_discovery/creator_profiles/tech_ai_creator.json"),
        generated_at="2026-06-30T10:00:00+08:00",
        topics=topics,
        results=results,
        evidence=evidence,
    )

    assert analysis["schema_version"] == "0.1"
    assert analysis["statistics"]["total_topics"] == 1
    assert analysis["statistics"]["total_results"] == 2
    assert analysis["statistics"]["total_evidence"] == 2
    assert analysis["statistics"]["source_distribution"] == {"github_search": 1, "baidu_qianfan_search": 1}
    assert analysis["statistics"]["keyword_distribution"] == {"AI Agent": 1, "MCP": 1}
    assert analysis["statistics"]["risk_distribution"] == {"low": 1}
    assert analysis["statistics"]["content_type_distribution"] == {"repo": 1, "web": 1}
    assert analysis["statistics"]["freshness_distribution"] == {"breaking": 1}
    assert analysis["statistics"]["score_buckets"] == {"80_plus": 0, "60_to_79": 1, "40_to_59": 0, "under_40": 0}
    assert analysis["statistics"]["recently_recommended_count"] == 1

    row = analysis["topics"][0]
    assert row["priority"] == "high"
    assert row["evidence_count"] == 2
    assert row["source_ids"] == ["github_search", "baidu_qianfan_search"]
    assert row["search_engines"] == ["GitHub Search", "Baidu Qianfan Search"]
    assert row["content_types"] == ["repo", "web"]
    assert row["rule_summary"]["recommended_format"] == "research_note"
    assert "recently recommended" in " ".join(row["rule_summary"]["verification_notes"])
    assert row["verification_summary"]["source_count"] == 2
    assert row["verification_summary"]["verification_score"] == 82
    assert row["verification_summary"]["evidence_level"] == "strong"
    assert row["verification_summary"]["has_clear_publish_time"] is True
    assert row["verification_summary"]["risk_label"] == "低"
    assert row["verification_summary"]["confidence_label"] == "高"
    assert row["suggested_titles"] == [
        "AI Agent 工具链，国内热点背后发生了什么？",
        "AI Agent 工具链为什么值得关注？一文梳理关键信号",
        "围绕AI Agent、MCP，AI Agent 工具链有哪些新变化？",
    ]
    assert row["evidence"][0]["source_type"] == "技术项目"
    assert row["evidence"][0]["source_name"] == "GitHub Search"
    assert row["llm_context"]["source_titles"] == ["agent/repo", "AI Agent 分析"]
    assert row["llm_context"]["evidence_bullets"][0].startswith("agent/repo:")


def test_build_topic_analysis_uses_medium_and_low_priorities():
    medium = _topic(topic_id="search_topic_002", topic_score=55, title="中等话题")
    low = _topic(topic_id="search_topic_003", topic_score=30, title="低分话题", risk_level="medium")

    analysis = build_topic_analysis(
        profile_path=Path("profile.json"),
        generated_at="2026-06-30T10:00:00+08:00",
        topics=[medium, low],
        results=[],
        evidence=[],
    )

    assert [topic["priority"] for topic in analysis["topics"]] == ["medium", "low"]
    assert analysis["statistics"]["score_buckets"] == {"80_plus": 0, "60_to_79": 0, "40_to_59": 1, "under_40": 1}


def test_build_topic_analysis_empty_input_is_stable():
    analysis = build_topic_analysis(
        profile_path=Path("profile.json"),
        generated_at="2026-06-30T10:00:00+08:00",
        topics=[],
        results=[],
        evidence=[],
    )

    assert analysis["statistics"]["total_topics"] == 0
    assert analysis["statistics"]["source_distribution"] == {}
    assert analysis["statistics"]["score_buckets"] == {"80_plus": 0, "60_to_79": 0, "40_to_59": 0, "under_40": 0}
    assert analysis["topics"] == []
    assert analysis["model_synthesis"] is None
    assert analysis["model_error"] is None
