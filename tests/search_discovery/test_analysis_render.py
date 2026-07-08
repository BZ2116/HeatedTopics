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
                "matched_keywords": ["AI Agent", "MCP"],
                "freshness": "breaking",
                "verification_summary": {
                    "source_count": 2,
                    "has_clear_publish_time": True,
                    "risk_label": "低",
                    "confidence_label": "高",
                    "notes": ["已有多个来源指向同一话题，基础可信度较高。"],
                },
                "suggested_titles": ["AI Agent 工具链，国内热点背后发生了什么？"],
                "rule_summary": {
                    "one_line_summary": "规则摘要",
                    "why_it_matters": "规则说明",
                    "creator_angles": ["项目拆解"],
                    "recommended_format": "research_note",
                    "verification_notes": ["核验规则"],
                },
                "evidence": [
                    {
                        "title": "agent/repo",
                        "url": "https://github.com/agent/repo",
                        "content_excerpt": "证据",
                        "source_type": "技术项目",
                        "source_name": "GitHub Search",
                        "published_at": "2026-06-30T09:00:00+08:00",
                        "evidence_confidence": "high",
                    }
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

    assert "# 国内热点匹配报告" in markdown
    assert "搜索结果总数：2 条" in markdown
    assert "## 一、本轮结论" in markdown
    assert "## 二、优先推荐选题" in markdown
    assert "| 优先级 | 话题 | 匹配度 | 可信度 | 时效性 | 风险 |" in markdown
    assert "## 三、话题详情" in markdown
    assert "规则摘要" in markdown
    assert "项目拆解" in markdown
    assert "| 来源类型 | 来源 | 标题 | 时间 | 可信度 |" in markdown
    assert "[agent/repo](https://github.com/agent/repo)" in markdown
    assert "## 四、需要谨慎处理的话题" in markdown
    assert "## 五、证据与来源统计" in markdown
    assert "## 六、关键词命中情况" in markdown


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

    assert "# 国内热点匹配报告" in markdown
    assert "本轮没有发现可用的国内热点候选话题。" in markdown
