from src.search_discovery.model_analysis import build_model_topic_analysis


def _analysis():
    return {
        "schema_version": "0.1",
        "generated_at": "2026-06-30T10:00:00+08:00",
        "statistics": {"total_topics": 2, "source_distribution": {"github_search": 1}},
        "topics": [
            {
                "topic_id": "search_topic_001",
                "title": "AI Agent 工具链",
                "priority": "high",
                "topic_score": 73,
                "risk_level": "low",
                "matched_keywords": ["AI Agent"],
                "rule_summary": {"one_line_summary": "规则摘要"},
                "llm_context": {
                    "compact_summary": "规则摘要",
                    "evidence_bullets": ["证据一"],
                    "source_titles": ["agent/repo"],
                    "risk_flags": ["低风险"],
                },
            },
            {
                "topic_id": "search_topic_002",
                "title": "MCP 安全",
                "priority": "medium",
                "topic_score": 55,
                "risk_level": "medium",
                "matched_keywords": ["MCP"],
                "rule_summary": {"one_line_summary": "规则摘要二"},
                "llm_context": {
                    "compact_summary": "规则摘要二",
                    "evidence_bullets": ["证据二"],
                    "source_titles": ["security"],
                    "risk_flags": ["中风险"],
                },
            },
        ],
    }


def test_build_model_topic_analysis_normalizes_valid_output():
    captured = {}

    def fake_model_call(messages):
        captured["messages"] = messages
        return {
            "overall_summary": {
                "core_conclusion": "核心结论",
                "topic_landscape": "话题格局",
                "creator_strategy": "创作者策略",
                "risk_and_verification": "核验提示",
            },
            "topic_suggestions": {
                "search_topic_001": {
                    "one_line_summary": "模型摘要",
                    "why_it_matters": "值得做",
                    "creator_angles": ["项目拆解", "工具对比"],
                    "recommended_format": "article",
                    "verification_notes": ["核验来源"],
                }
            },
        }

    result = build_model_topic_analysis(
        analysis=_analysis(),
        model_call=fake_model_call,
        model="gpt-test",
        generated_at="2026-06-30T10:00:00+08:00",
        max_topics=1,
    )

    assert result["mode"] == "model"
    assert result["model"] == "gpt-test"
    assert result["overall_summary"]["core_conclusion"] == "核心结论"
    assert result["topic_suggestions"]["search_topic_001"]["creator_angles"] == ["项目拆解", "工具对比"]
    assert "search_topic_002" not in captured["messages"][1]["content"]


def test_build_model_topic_analysis_normalizes_missing_fields():
    def fake_model_call(messages):
        return {"overall_summary": {}, "topic_suggestions": {"search_topic_001": {"creator_angles": "not-list"}}}

    result = build_model_topic_analysis(
        analysis=_analysis(),
        model_call=fake_model_call,
        model="gpt-test",
        generated_at="2026-06-30T10:00:00+08:00",
    )

    suggestion = result["topic_suggestions"]["search_topic_001"]
    assert result["overall_summary"]["creator_strategy"] == ""
    assert suggestion["one_line_summary"] == ""
    assert suggestion["creator_angles"] == []
    assert suggestion["verification_notes"] == []


def test_build_model_topic_analysis_returns_error_when_model_raises():
    def fake_model_call(messages):
        raise RuntimeError("missing key")

    result = build_model_topic_analysis(
        analysis=_analysis(),
        model_call=fake_model_call,
        model="gpt-test",
        generated_at="2026-06-30T10:00:00+08:00",
    )

    assert result["error_type"] == "RuntimeError"
    assert "missing key" in result["message"]
    assert result["mode"] == "model_error"
