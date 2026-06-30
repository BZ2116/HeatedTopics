from src.search_discovery.api_config import api_source_configs, get_api_source_config, mask_secret


def test_api_source_configs_include_all_configurable_sources():
    configs = api_source_configs()

    assert configs["github_search"].env_keys == ["GITHUB_TOKEN"]
    assert configs["baidu_qianfan_search"].env_keys == ["QIANFAN_API_KEY", "QIANFAN_SECRET_KEY"]
    assert configs["tavily_search"].env_keys == ["TAVILY_API_KEY"]
    assert configs["tianapi_news"].test_query == "AI Agent 最新进展"


def test_get_api_source_config_rejects_unknown_source():
    try:
        get_api_source_config("missing_source")
    except KeyError as exc:
        assert "missing_source" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_mask_secret_keeps_short_preview_only():
    assert mask_secret("") == "<empty>"
    assert mask_secret("abc") == "***"
    assert mask_secret("tvly_1234567890") == "tvly****7890"