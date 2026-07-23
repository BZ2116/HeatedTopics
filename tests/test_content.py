import heated_topics_v3.content as content_module
from heated_topics_v3.content import extract_container_text, validate_full_text
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


def test_rejects_repeated_summary_and_title_summary_with_metadata_suffix():
    title = "多地发布重要天气预警"
    summary = "气象部门预计本轮强降雨将持续影响多个地区，相关部门已启动应急响应并提醒公众注意出行安全。"

    repeated = validate_full_text(
        "\n\n".join((summary, summary, summary)),
        title,
        summary,
    )
    assert repeated.status == "rejected"
    assert "title_or_summary" in repeated.reasons

    combined = validate_full_text(
        "\n\n".join((title, summary, f"{summary} 来源：公开信息")),
        title,
        summary,
    )
    assert combined.status == "rejected"
    assert "title_or_summary" in combined.reasons


def test_native_validation_cannot_be_relabelled_as_gne_without_revalidation():
    content = "\n\n".join(
        [
            "第一段介绍事件背景，包含明确的人物、时间和地点，并说明事件起因。",
            "第二段描述事件进展，引用公开信息并补充相关数据和各方回应。",
            "第三段交代后续安排、影响范围以及仍需继续确认的信息。",
        ]
    )
    assert validate_full_text(content, "事件标题", "事件摘要").status == "accepted"
    assert not hasattr(content_module, "with_parser")
    assert (
        validate_full_text(content, "事件标题", "事件摘要", parser="gne").status
        == "rejected"
    )


def test_inline_text_nodes_do_not_create_fake_paragraphs():
    html = (
        '<div id="article"><p>'
        f"<span>{'正文内容' * 11}</span>"
        f"<span>{'继续报道' * 11}</span>"
        "</p></div>"
    )
    content = extract_container_text(html, ("#article",))
    assert "\n" not in content
    result = validate_full_text(content, "事件标题", "")
    assert result.status == "rejected"
    assert "insufficient_structure" in result.reasons


def test_nested_ignored_content_does_not_leak_text_after_container():
    paragraphs = (
        "第一段介绍事件背景，包含明确的人物、时间和地点，并说明事件起因。",
        "第二段描述事件进展，引用公开信息并补充相关数据和各方回应。",
        "第三段交代后续安排、影响范围以及仍需继续确认的信息。",
    )
    html = (
        '<div id="article">'
        f"<p>{paragraphs[0]}</p>"
        "<nav><div><span>登录后发表评论 推荐阅读</span></div></nav>"
        f"<p>{paragraphs[1]}</p><p>{paragraphs[2]}</p>"
        "</div>"
        "<div>登录后发表评论 推荐阅读 返回首页 相关阅读</div>"
    )
    content = extract_container_text(html, ("#article",))
    assert content.splitlines() == list(paragraphs)
    assert validate_full_text(content, "事件标题", "事件摘要").status == "accepted"
