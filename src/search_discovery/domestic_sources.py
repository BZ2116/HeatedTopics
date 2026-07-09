from src.search_discovery.types import PlannedSource


# 每类 intent 对应的 source 优先级和权重
DOMESTIC_SOURCE_PRIORITIES = {
    "news_trend": [
        PlannedSource("tianapi_news", 95),
        PlannedSource("news_api_cn", 90),
        PlannedSource("baidu_qianfan_search", 85),
        PlannedSource("tavily_search", 78),
        PlannedSource("qiniu_web_search", 70),
    ],
    "deep_article": [
        PlannedSource("baidu_qianfan_search", 90),
        PlannedSource("news_api_cn", 85),
        PlannedSource("tavily_search", 78),
        PlannedSource("qiniu_web_search", 70),
        PlannedSource("juejin_content", 60),
    ],
    "product_trend": [
        PlannedSource("baidu_qianfan_search", 90),
        PlannedSource("news_api_cn", 85),
        PlannedSource("tianapi_news", 80),
        PlannedSource("tavily_search", 78),
        PlannedSource("qiniu_web_search", 70),
    ],
}

# 内容角度 → query suffix（面向创作者，找具体事件而不是行业概览）
CONTENT_MODE_QUERY_SUFFIXES = [
    # 平台热门（优先，靠前的 suffix 被 [:6] 截取后仍能覆盖）
    "小红书 微博 热门 爆款",
    # 事件驱动
    "融资 发布 重大更新",
    "争议 暴雷 内卷 乱象",
    "裁员 收缩 转型 调整",
    # 问题驱动
    "还能做吗 还能入局吗 红利",
    "机会 红利 新方向 破局",
    # 实战角度
    "避坑 教训 踩雷 真实经历",
    "真实经历 实测 测评 对比",
    # 复盘分析
    "复盘 分析 解读 深度",
    # 政策监管
    "政策 补贴 监管 规范",
]

# 兜底 suffix（当 content_modes 为空时用）
FALLBACK_QUERY_SUFFIXES = [
    "融资 发布 重大更新",
    "争议 内卷 暴雷",
    "真实经历 实测 避坑",
    "复盘 分析 解读",
    "政策 补贴 新规",
    "小红书 微博 热门 爆款",
]


def domestic_source_plan(intent: str) -> list[PlannedSource]:
    return DOMESTIC_SOURCE_PRIORITIES.get(intent, [])


def build_source_queries(source_id: str, keywords: str, intent: str, content_modes: list[str]) -> list[tuple[str, str]]:
    """
    返回 list of (query, query_angle)，每个 source 生成多个不同角度的 query。
    """
    suffixes = CONTENT_MODE_QUERY_SUFFIXES if content_modes else FALLBACK_QUERY_SUFFIXES
    if source_id == "tavily_search":
        suffix_map = {
            "融资 发布 重大更新": "funding news product launch",
            "争议 暴雷 内卷 乱象": "controversy scandal backlash",
            "裁员 收缩 转型 调整": "layoffs pivot restructuring",
            "还能做吗 还能入局吗 红利": "opportunity market potential",
            "机会 红利 新方向 破局": "breakthrough new opportunity",
            "避坑 教训 踩雷 真实经历": "real experience review tips",
            "真实经历 实测 测评 对比": "review comparison hands-on",
            "复盘 分析 解读 深度": "analysis deep dive review",
            "政策 补贴 新规": "policy regulation subsidy",
            "小红书 热门 爆款 种草": "Xiaohongshu trending viral china",
            "微博热搜 话题 热议": "Weibo trending topic china",
        }
        return [(f"{keywords} {suffix_map.get(s, s)}", s) for s in suffixes[:6]]

    # 国内 source 用中文 suffix
    return [(f"{keywords} {s}", s) for s in suffixes[:6]]
