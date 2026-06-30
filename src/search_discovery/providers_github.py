import os

import httpx

from src.search_discovery.base_provider import BaseHTTPSearchProvider


class GitHubSearchProvider(BaseHTTPSearchProvider):
    source_id = "github_search"
    rpm_limit = 30  # GitHub secondary rate limit; stay conservative
    timeout_seconds = 10.0

    def __init__(self, *, token: str | None = None, transport: httpx.BaseTransport | None = None):
        super().__init__(transport=transport)
        self._token = token

    @classmethod
    def from_env(cls) -> "GitHubSearchProvider | None":
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return None
        return cls(token=token)

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "heatedTopics/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _build_request(self, query: str) -> httpx.Request:
        return httpx.Request(
            "GET",
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 10},
            headers=self._auth_headers(),
        )

    def _parse_response(self, response: httpx.Response, query: str) -> list[dict[str, object]]:
        body = response.json()
        rows: list[dict[str, object]] = []
        for item in body.get("items", []):
            url = item.get("html_url", "")
            if not url:
                continue
            license_info = item.get("license") or {}
            metrics = {
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "watchers": item.get("watchers_count", 0),
                "open_issues": item.get("open_issues_count", 0),
                "language": item.get("language") or "Unknown",
                "topics": item.get("topics", []),
                "pushed_at": item.get("pushed_at", ""),
                "updated_at": item.get("updated_at", ""),
                "license": license_info.get("spdx_id", "") if isinstance(license_info, dict) else "",
            }
            rows.append({
                "title": item.get("full_name", ""),
                "url": url,
                "domain": "github.com",
                "snippet": item.get("description", "") or "",
                "content_type": "repo",
                "published_at": str(item.get("updated_at", "") or item.get("pushed_at", "")),
                "metrics": metrics,
                "raw_payload": {
                    "full_name": item.get("full_name", ""),
                    "html_url": url,
                    "description": item.get("description", "") or "",
                    "owner": item.get("owner", {}),
                },
            })
        return rows
