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


def test_clean_topic_content_removes_weibo_author_time_and_count_noise():
    raw = """
    1
    央视新闻
    今天15:00 来自 微博网页版
    #高考分数线#【#河北分数线#发布转给考生！】今天，#河北高考分数线#公布。
    340
    524
    4432
    """

    cleaned = clean_topic_content("河北高考分数线", raw)

    assert "\n1\n" not in f"\n{cleaned.clean_content}\n"
    assert "央视新闻" not in cleaned.clean_content
    assert "来自 微博网页版" not in cleaned.clean_content
    assert "\n340\n" not in f"\n{cleaned.clean_content}\n"
    assert "河北高考分数线#公布" in cleaned.clean_content


def test_clean_topic_content_removes_video_overlay_and_baidu_event_chrome():
    raw = """
    弹幕互动
    
    江苏2026高考分数线公布 百度首页 登录 江苏2026高考分数线公布 更新至2026年6月24日 17:20 发表    换一换 
    刚刚
    今天15:36
    刚刚，2026江苏高考分数线公布：特殊类历史532/物理513，本科历史484/物理456。
    """

    cleaned = clean_topic_content("江苏2026高考分数线公布", raw)

    assert "弹幕互动" not in cleaned.clean_content
    assert "百度首页 登录" not in cleaned.clean_content
    assert "换一换" not in cleaned.clean_content
    assert "\n刚刚\n" not in f"\n{cleaned.clean_content}\n"
    assert "特殊类历史532/物理513" in cleaned.clean_content


def test_clean_topic_content_removes_inline_weibo_tail_and_media_noise():
    raw = """
    北京日报
    今天13:53 来自 恋与深空超话
    【媒体评：#恋与深空新男主为何引争议# 】角色因空降式登场方式引发争议。 ​ 展开c
    播放视频
    https://video.weibo.com/show?fid=1034:5313331246858282
    千问
    广告 06月22日 10:00 来自 微博视频号
    查分后就要选志愿啦！跟着千问高考志愿Agent选志愿。
    """

    cleaned = clean_topic_content("恋与深空新男主为何引争议", raw)

    assert "北京日报" not in cleaned.clean_content
    assert "来自 恋与深空超话" not in cleaned.clean_content
    assert "展开c" not in cleaned.clean_content
    assert "播放视频" not in cleaned.clean_content
    assert "video.weibo.com" not in cleaned.clean_content
    assert "广告 06月22日" not in cleaned.clean_content
    assert "角色因空降式登场方式引发争议" in cleaned.clean_content
    assert "跟着千问高考志愿Agent选志愿" not in cleaned.clean_content


def test_clean_topic_content_removes_baidu_hot_list_container_noise():
    raw = """
    男生高考358分 全家激动落泪 百度首页 登录 男生高考358分 全家激动落泪 更新至2026年6月24日 17:21 发表    换一换 
    热搜榜第5名
    百度热搜 新闻 hao123 地图 视频 贴吧 学术 更多 百度首页 登录 首页 热搜 小说 电影 电视剧 首页 热搜 小说 电影 电视剧 热搜榜 更多 从一艘小船到一个大党 1 两名日本人违反中国法律被依法拘留 2 江苏2026高考分数线公布 热 3 消费品以旧换新带动销售额5万亿元 4 普京：行动开始前我们已忍耐8年 新 5 男生高考358分 全家激动落泪 6 “最脏水果”第一名 小心一口就中招 7 高考查分 8 男子取款1万ATM机只吐5千 银行回应 新 9 李在明怒斥女消防员被强迫陪酒致死 10 2026年各地高考分数线汇总 新 11 一盘蚊香=几十支烟？专家辟谣 12 火箭军一级军士长：要做好打仗的准备 热 13 别再随便买路
    """

    cleaned = clean_topic_content("男生高考358分 全家激动落泪", raw)

    assert cleaned.clean_content == "男生高考358分 全家激动落泪"
    assert "2026年6月24日 17:21 发表" not in cleaned.clean_content
    assert "热搜榜第5名" not in cleaned.clean_content
    assert "百度热搜 新闻 hao123" not in cleaned.clean_content
    assert "一盘蚊香" not in cleaned.clean_content


def test_clean_topic_content_removes_inline_links_and_numbered_list_tail():
    raw = """
    江苏2026高考分数线公布：特殊类历史532/物理513，本科历史484/物理456。 https://example.com/detail
    百度热搜 新闻 hao123 地图 视频 贴吧 更多 热搜榜 更多 1 两名日本人违反中国法律被依法拘留 2 江苏2026高考分数线公布 热 3 消费品以旧换新带动销售额5万亿元 4 高考查分
    """

    cleaned = clean_topic_content("江苏2026高考分数线公布", raw)

    assert "特殊类历史532/物理513" in cleaned.clean_content
    assert "https://example.com/detail" not in cleaned.clean_content
    assert "百度热搜 新闻 hao123" not in cleaned.clean_content
    assert "两名日本人违反中国法律" not in cleaned.clean_content
    assert "消费品以旧换新" not in cleaned.clean_content


def test_clean_topic_content_normalizes_title_url_placeholder_rows():
    raw = """
    Title: 2026年河北省高考分数线公布
    URL:
    """

    cleaned = clean_topic_content("2026年河北省高考分数线公布", raw)

    assert cleaned.clean_content == "2026年河北省高考分数线公布"
    assert "Title:" not in cleaned.clean_content
    assert "URL:" not in cleaned.clean_content


def test_clean_topic_content_drops_ad_block_after_ad_metadata():
    raw = """
    #河北高考分数线#公布，本科批历史485分，物理443分。
    千问
    广告 06月22日 10:00 来自 微博视频号
    查分后就要选志愿啦！跟着千问高考志愿Agent选志愿。
    【AI志愿报告】为你量身定制，冲稳保方案。
    """

    cleaned = clean_topic_content("河北高考分数线", raw)

    assert "本科批历史485分" in cleaned.clean_content
    assert "千问" not in cleaned.clean_content
    assert "高考志愿Agent" not in cleaned.clean_content
    assert "AI志愿报告" not in cleaned.clean_content


def test_clean_topic_content_removes_ai_widget_and_javascript_noise():
    raw = """
    河北高考分数线公布，本科批历史485分，物理443分。
    千问
    【AI志愿日历】全程指引每一步，在每个节点提醒你。
    智搜回答
    5分钟前 深度思考(DS-R1·AI生成)
    江苏2026高考分数线公布 在线查分 您需要先启用javascript功能 高考批次线 您需要先启用javascript功能
    """

    cleaned = clean_topic_content("河北高考分数线", raw)

    assert "河北高考分数线公布" in cleaned.clean_content
    assert "千问" not in cleaned.clean_content
    assert "AI志愿日历" not in cleaned.clean_content
    assert "智搜回答" not in cleaned.clean_content
    assert "深度思考" not in cleaned.clean_content
    assert "javascript" not in cleaned.clean_content.lower()


def test_clean_topic_content_removes_xinhua_article_template_tail_and_inline_controls():
    raw = """
    两名日本人违反中国法律被依法拘留
    两名日本人因违反中国法律被中方主管部门依法拘留-新华网
    两名日本人因违反中国法律被中方主管部门依法拘留-新华网 新华网 > > 正文 2026 06 / 24 15:29:42 来源：新华网 两名日本人因违反中国法律被中方主管部门依法拘留 字体： 小 中 大 分享到： 两名日本人因违反中国法律被中方主管部门依法拘留 2026-06-24 15:29:42 来源：新华网 新华社北京6月24日电（记者吴梦桐、马卓言）针对有报道说两名日本人在大连被拘留，外交部发言人郭嘉昆24日在例行记者会上答问时表示，据了解，两名日本人因违反中国法律被中方主管部门依法拘留，中方已向日方通报了有关个案情况。我们想强调的是，日方应教育提醒在华日本公民和企业遵守中国法律法规。 【纠错】 【责任编辑:邱丽芳】 阅读下一篇： 深度观察 新华全媒头条丨 呼和浩特绿色算力产业发展观察 高端访谈丨非盟轮值主席：非中关系是南南合作的典范
    """

    cleaned = clean_topic_content("两名日本人违反中国法律被依法拘留", raw)

    assert "新华社北京6月24日电" in cleaned.clean_content
    assert cleaned.clean_content.count("两名日本人因违反中国法律被中方主管部门依法拘留") <= 1
    assert "字体： 小 中 大" not in cleaned.clean_content
    assert "分享到" not in cleaned.clean_content
    assert "【责任编辑" not in cleaned.clean_content
    assert "阅读下一篇" not in cleaned.clean_content
    assert "呼和浩特绿色算力产业发展观察" not in cleaned.clean_content
