from dataclasses import dataclass


@dataclass(frozen=True)
class ApiSourceConfig:
    source_id: str
    display_name: str
    env_keys: list[str]
    signup_url: str
    description: str
    test_query: str = "AI Agent 最新进展"


def api_source_configs() -> dict[str, ApiSourceConfig]:
    return {
        "github_search": ApiSourceConfig(
            source_id="github_search",
            display_name="GitHub Search",
            env_keys=["GITHUB_TOKEN"],
            signup_url="https://github.com/settings/tokens",
            description="Open-source repository and project discovery.",
            test_query="AI Agent stars:>50 pushed:>2025-01-01",
        ),
        "news_api_cn": ApiSourceConfig(
            source_id="news_api_cn",
            display_name="Bocha AI Search",
            env_keys=["BOCHA_API_KEY"],
            signup_url="https://bochaai.com",
            description="AI-friendly China web and news search.",
        ),
        "juejin_content": ApiSourceConfig(
            source_id="juejin_content",
            display_name="Aliyun Bailian Web Search",
            env_keys=["BAILIAN_API_KEY"],
            signup_url="https://bailian.console.aliyun.com/",
            description="Chinese technical articles and web search slot.",
        ),
        "baidu_qianfan_search": ApiSourceConfig(
            source_id="baidu_qianfan_search",
            display_name="Baidu Qianfan Search",
            env_keys=["QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"],
            signup_url="https://console.bce.baidu.com/qianfan/",
            description="Domestic general web, blog, Q&A, and news search.",
        ),
        "tianapi_news": ApiSourceConfig(
            source_id="tianapi_news",
            display_name="TianAPI News",
            env_keys=["TIANAPI_KEY"],
            signup_url="https://www.tianapi.com/",
            description="China news facts, source names, and publish times.",
        ),
        "tavily_search": ApiSourceConfig(
            source_id="tavily_search",
            display_name="Tavily Search",
            env_keys=["TAVILY_API_KEY"],
            signup_url="https://app.tavily.com/home",
            description="AI-friendly web/news search with summaries and raw content.",
        ),
        "qiniu_web_search": ApiSourceConfig(
            source_id="qiniu_web_search",
            display_name="Qiniu Web Search",
            env_keys=["QINIU_WEB_SEARCH_API_KEY"],
            signup_url="https://www.qiniu.com/",
            description="Domestic web-search fallback source.",
        ),
    }


def get_api_source_config(source_id: str) -> ApiSourceConfig:
    configs = api_source_configs()
    if source_id not in configs:
        raise KeyError(f"Unknown API source: {source_id}")
    return configs[source_id]


def mask_secret(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return "***"
    return f"{value[:4]}****{value[-4:]}"