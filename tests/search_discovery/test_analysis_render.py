from src.search_discovery.analysis_render import render_topic_analysis_markdown


def _analysis(model=False):
    payload = {
        "generated_at": "2026-06-30T10:00:00+08:00",
        "statistics": {
            "total_topics": 1,
            "total_results": 2,
            "total_evidence": 2,
            "source_distribution": {"github_search": 1},
            "keyword_distribution": {"AI Agent": 1},
            "risk_distribution": {"low": 1},
            "content_type_distribution": {"repo": 1},
            "freshness_distribution": {"breaking": 1},
            "score_buckets": {"80_plus": 0, "60_to_79": 1, "40_to_59": 0, "under_40": 0},
            "recently_recommended_count": 0,
        },
        "topics": [
            {
                "topic_id": "search_topic_001",
                "title": "AI Agent 工具链",
                "priority": "high",
                "topic_score": 73,
                "risk_level": "low",
                "rule_summary": {
                    "one_line_summary": "规则摘要",
                    "why_it_matters": "规则说明",
                    "creator_angles": ["项目拆解"],
                    "recommended_format": "research_note",
                    "verification_notes": ["核验规则"],
                },
                "evidence": [
                    {"title": "agent/repo", "url": "https://github.com/agent/repo", "content_excerpt": "证据"}
                ],
            }
        ],
        "model_synthesis": None,
        "model_error": None,
    }
    if model:
        payload["model_synthesis"] = {
            "overall_summary": {
                "core_conclusion": "模型总判断",
                "topic_landscape": "模型格局",
                "creator_strategy": "模型策略",
                "risk_and_verification": "模型核验",
            },
            "topic_suggestions": {
                "search_topic_001": {
                    "one_line_summary": "模型摘要",
                    "why_it_matters": "模型价值",
                    "creator_angles": ["模型角度"],
                    "recommended_format": "article",
                    "verification_notes": ["模型核验点"],
                }
            },
        }
    return payload


def test_render_topic_analysis_markdown_uses_rule_fallback():
    markdown = render_topic_analysis_markdown(_analysis())

    assert "# 选题分析报告" in markdown
    assert "## 本轮概览" in markdown
    assert "共 1 个候选话题" in markdown
    assert "规则摘要" in markdown
    assert "项目拆解" in markdown
    assert "[agent/repo](https://github.com/agent/repo)" in markdown
    assert "## 统计附录" in markdown


def test_render_topic_analysis_markdown_prefers_model_text():
    markdown = render_topic_analysis_markdown(_analysis(model=True))

    assert "模型总判断" in markdown
    assert "模型摘要" in markdown
    assert "模型角度" in markdown
    assert "模型核验点" in markdown
    assert "规则摘要" not in markdown


def test_render_topic_analysis_markdown_handles_empty_topics():
    markdown = render_topic_analysis_markdown(
        {
            "generated_at": "2026-06-30T10:00:00+08:00",
            "statistics": {"total_topics": 0, "total_results": 0, "total_evidence": 0},
            "topics": [],
            "model_synthesis": None,
            "model_error": None,
        }
    )

    assert "No usable search topics were found." in markdown