REQUIRED_DETAIL_PLATFORMS = ("weibo", "xiaohongshu", "baidu")

PRIMARY_HOT_ROUTES = ("weibo", "xiaohongshu", "baidu")

DAILYHOT_ROUTE_GROUPS = {
    "core_discovery": (
        "weibo",
        "xiaohongshu",
        "baidu",
        "zhihu",
        "toutiao",
    ),
    "auxiliary_news": (
        "sina-news",
        "thepaper",
        "qq-news",
        "netease-news",
    ),
    "auxiliary_tech_business": (
        "36kr",
        "ithome",
        "juejin",
        "csdn",
    ),
    "foreign_tech": (
        "github",
        "hellogithub",
    ),
    "auxiliary_content_heat": (
        "bilibili",
        "douyin",
        "kuaishou",
    ),
}

FAILED_DEFAULT_ROUTES = (
    "coolapk",
    "earthquake",
    "hackernews",
    "hostloc",
    "linuxdo",
    "nodeseek",
    "nytimes",
    "producthunt",
    "sspai",
    "v2ex",
)

AUXILIARY_DAILYHOT_ROUTES = tuple(
    route
    for group_name, routes in DAILYHOT_ROUTE_GROUPS.items()
    if group_name != "core_discovery"
    for route in routes
)

ALL_DAILYHOT_ROUTES = tuple(
    route
    for routes in DAILYHOT_ROUTE_GROUPS.values()
    for route in routes
)


def route_role(route: str) -> str:
    for group_name, routes in DAILYHOT_ROUTE_GROUPS.items():
        if route in routes:
            return group_name
    return "unknown"


DETAIL_ENABLED_PLATFORMS = ("weibo", "baidu", "xiaohongshu", "bilibili", "juejin")

DETAIL_PLATFORM_LIMITS = {
    "weibo": 20,
    "xiaohongshu": 20,
    "baidu": 80,
    "bilibili": 80,
    "juejin": 30,
}


def platform_detail_enabled(platform: str, enabled_platforms: tuple[str, ...] = DETAIL_ENABLED_PLATFORMS) -> bool:
    return platform in enabled_platforms
