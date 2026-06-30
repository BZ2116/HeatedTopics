from dataclasses import dataclass

from src.search_discovery.providers import MockProvider, SearchProviderRegistry


@dataclass(frozen=True)
class ConnectionTestResult:
    source_id: str
    status: str
    message: str
    result_count: int = 0
    error_type: str = ""


def test_source_connection(
    source_id: str,
    *,
    registry: SearchProviderRegistry,
    query: str,
) -> ConnectionTestResult:
    provider = registry.providers.get(source_id)
    if provider is None or isinstance(provider, MockProvider):
        return ConnectionTestResult(
            source_id=source_id,
            status="missing_key",
            message=f"{source_id} is not configured.",
            error_type="missing_key",
        )

    rows = provider.search_rows(query, keyword_category="connection_test", fetched_at="", index=0)
    error_rows = [row for row in rows if str(row.get("fetch_status", "ok")) != "ok"]
    if error_rows:
        first = error_rows[0]
        status = str(first.get("fetch_status", "upstream_failed"))
        error_type = str(first.get("error_type", "unknown"))
        return ConnectionTestResult(
            source_id=source_id,
            status=status,
            message=f"{source_id} {status}: {error_type}",
            error_type=error_type,
        )
    if not rows:
        return ConnectionTestResult(
            source_id=source_id,
            status="empty_result",
            message=f"{source_id} connected but returned no results.",
            result_count=0,
        )
    return ConnectionTestResult(
        source_id=source_id,
        status="ok",
        message=f"{source_id} connected successfully, returned {len(rows)} results.",
        result_count=len(rows),
    )


test_source_connection.__test__ = False