from dataclasses import dataclass

from src.search_discovery.connectivity import ConnectionTestResult, test_source_connection
from src.search_discovery.providers import MockProvider, SearchProviderRegistry


@dataclass
class FakeProvider:
    source_id: str
    rows: list[dict[str, object]]

    def search_rows(self, query, **kwargs):
        return self.rows


def test_test_source_connection_reports_missing_key_for_mock_provider():
    registry = SearchProviderRegistry([MockProvider("tavily_search", rows=[])])

    result = test_source_connection("tavily_search", registry=registry, query="AI Agent 最新进展")

    assert result == ConnectionTestResult(
        source_id="tavily_search",
        status="missing_key",
        message="tavily_search is not configured.",
        result_count=0,
        error_type="missing_key",
    )


def test_test_source_connection_reports_ok_when_rows_returned():
    registry = SearchProviderRegistry([
        FakeProvider("tavily_search", [{"title": "A", "url": "https://example.com", "snippet": "summary"}])
    ])

    result = test_source_connection("tavily_search", registry=registry, query="AI Agent 最新进展")

    assert result.status == "ok"
    assert result.result_count == 1
    assert "connected successfully" in result.message


def test_test_source_connection_reports_provider_error_row():
    registry = SearchProviderRegistry([
        FakeProvider(
            "baidu_qianfan_search",
            [{"fetch_status": "auth_failed", "error_type": "token_exchange_failed", "title": "", "url": ""}],
        )
    ])

    result = test_source_connection("baidu_qianfan_search", registry=registry, query="AI Agent 最新进展")

    assert result.status == "auth_failed"
    assert result.error_type == "token_exchange_failed"
    assert "token_exchange_failed" in result.message