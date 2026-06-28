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
        headers = {"Accept": "application/vnd.github+json"}
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
            rows.append({
                "title": item.get("full_name", ""),
                "url": url,
                "domain": "github.com",
                "snippet": item.get("description", "") or "",
                "content_type": "repo",
                "published_at": "",
                "metrics": {"stars": item.get("stargazers_count", 0)},
            })
        return rows