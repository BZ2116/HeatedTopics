from heated_topics_v3.hot_topics.research_provider import (
    McpWebSearchProvider,
    MiniMaxMcpResearchProvider,
    build_web_search_provider,
)


def test_default_backend_keeps_minimax_compatibility(monkeypatch):
    monkeypatch.delenv("HT_WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    provider = build_web_search_provider()
    assert isinstance(provider, MiniMaxMcpResearchProvider)
    assert provider.command == "uvx"
    assert provider.tool_name == "web_search"
    assert provider.env["MINIMAX_API_KEY"] == "test-key"


def test_generic_mcp_backend_is_configurable(monkeypatch):
    monkeypatch.setenv("HT_WEB_SEARCH_PROVIDER", "generic_mcp")
    monkeypatch.setenv("HT_WEB_SEARCH_MCP_COMMAND", "custom-mcp")
    monkeypatch.setenv("HT_WEB_SEARCH_MCP_ARGS", "--stdio --profile default")
    monkeypatch.setenv("HT_WEB_SEARCH_MCP_TOOL", "search")
    monkeypatch.setenv("HT_WEB_SEARCH_MCP_ENV_JSON", '{"SEARCH_TOKEN":"secret"}')
    provider = build_web_search_provider()
    assert isinstance(provider, McpWebSearchProvider)
    assert not isinstance(provider, MiniMaxMcpResearchProvider)
    assert provider.args == ["--stdio", "--profile", "default"]
    assert provider.tool_name == "search"
    assert provider.env == {"SEARCH_TOKEN": "secret"}


def test_generic_mcp_requires_command_arguments(monkeypatch):
    monkeypatch.setenv("HT_WEB_SEARCH_PROVIDER", "generic_mcp")
    monkeypatch.delenv("HT_WEB_SEARCH_MCP_ARGS", raising=False)
    try:
        build_web_search_provider()
    except ValueError as exc:
        assert "HT_WEB_SEARCH_MCP_ARGS" in str(exc)
    else:
        raise AssertionError("generic MCP without args must fail clearly")
