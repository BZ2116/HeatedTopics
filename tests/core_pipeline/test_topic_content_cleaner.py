from src.core_pipeline.topic_content_cleaner import clean_topic_content


def test_clean_topic_content_removes_common_page_chrome():
    raw = """
    NEW
    1
    搜索结果
    综合
    智搜
    实时
    用户
    视频
    图片
    话题
    高级搜索
    热门
    c
    央视新闻 今天15:00 来自 微博网页版
    河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。
    展开c
    下一页
    """

    cleaned = clean_topic_content("河北高考分数线", raw)

    assert "搜索结果" not in cleaned.clean_content
    assert "高级搜索" not in cleaned.clean_content
    assert "展开c" not in cleaned.clean_content
    assert "河北高考分数线公布" in cleaned.clean_content
    assert "物理科目组合443分" in cleaned.clean_content


def test_clean_topic_content_drops_unrelated_hot_list_sidebar_lines():
    raw = """
    从一艘小船到一个大党
    相关新闻正文第一段。
    百度热搜
    1 两名日本人违反中国法律被依法拘留
    2 江苏2026高考分数线公布
    3 消费品以旧换新带动销售额5万亿元
    4 高考查分
    """

    cleaned = clean_topic_content("从一艘小船到一个大党", raw)

    assert "相关新闻正文第一段" in cleaned.clean_content
    assert "江苏2026高考分数线公布" not in cleaned.clean_content
    assert "高考查分" not in cleaned.clean_content


def test_clean_topic_content_preserves_raw_preview_and_limits_clean_content():
    raw = "标题\n" + "\n".join(f"正文第{index}行，包含有效信息。" for index in range(80))

    cleaned = clean_topic_content("标题", raw, max_clean_chars=120, max_raw_preview_chars=30)

    assert cleaned.raw_content_preview.startswith("标题")
    assert len(cleaned.raw_content_preview) <= 30
    assert len(cleaned.clean_content) <= 120
    assert cleaned.content_quality in {"clean", "partial"}


def test_clean_topic_content_falls_back_to_title_when_raw_text_is_empty():
    cleaned = clean_topic_content("河北高考分数线", "")

    assert cleaned.clean_content == "河北高考分数线"
    assert cleaned.content_quality == "fallback"