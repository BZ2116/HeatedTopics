from heated_topics_v3.content import validate_full_text
from heated_topics_v3.contracts import ContentValidation


def test_full_text_accepts_real_multi_paragraph_article():
    content = "\n\n".join(
        [
            "第一段介绍事件背景，包含明确的人物、时间和地点，并说明事件起因。",
            "第二段描述事件进展，引用公开信息并补充相关数据和各方回应。",
            "第三段交代后续安排、影响范围以及仍需继续确认的信息。",
        ]
    )
    result = validate_full_text(content, "事件标题", "事件摘要")
    assert result == ContentValidation(
        status="accepted",
        parser="",
        character_count=len("".join(content.split())),
        paragraph_count=3,
        reasons=(),
    )


def test_full_text_rejects_summary_title_and_page_chrome():
    assert validate_full_text("事件标题", "事件标题", "").status == "rejected"
    assert validate_full_text("只有一句摘要。", "事件标题", "只有一句摘要。").status == "rejected"
    chrome = ("登录后发表评论 推荐阅读 返回首页 " * 30).strip()
    result = validate_full_text(chrome, "事件标题", "")
    assert result.status == "rejected"
    assert "page_chrome" in result.reasons


def test_gne_fallback_keeps_stricter_two_hundred_character_floor():
    content = "\n\n".join(
        [
            "第一段介绍事件背景，包含明确的人物、时间和地点，并说明事件起因。",
            "第二段描述事件进展，引用公开信息并补充相关数据和各方回应。",
            "第三段交代后续安排、影响范围以及仍需继续确认的信息。",
        ]
    )
    result = validate_full_text(
        content, "事件标题", "事件摘要", parser="gne"
    )
    assert result.status == "rejected"
    assert "too_short" in result.reasons
