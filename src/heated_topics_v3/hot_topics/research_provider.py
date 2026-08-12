"""Adapters for citation-bearing Web Search services."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import asyncio
import json
import os
import shlex
import threading
from concurrent.futures import Future
from typing import Mapping, Protocol, Sequence

import httpx

from .research_contracts import SearchEvidence


def deduplicate_evidence(items: tuple[SearchEvidence, ...] | list[SearchEvidence]) -> tuple[SearchEvidence, ...]:
    """Drop exact reposts while preserving distinct factual evidence."""
    seen: set[tuple[str, str]] = set()
    kept: list[SearchEvidence] = []
    for item in items:
        key = (
            re.sub(r"\W+", "", item.title.lower()),
            re.sub(r"\W+", "", item.snippet.lower()),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return tuple(kept)


class ResearchProvider(Protocol):
    def search(self, query: str, *, topic_id: str) -> tuple[SearchEvidence, ...]: ...


class HttpResearchProvider:
    def __init__(self, endpoint: str, *, client: httpx.Client | None = None, provider_name: str = "llm_web_search") -> None:
        self.endpoint = endpoint
        self.client = client or httpx.Client(timeout=30.0)
        self.provider_name = provider_name

    def search(self, query: str, *, topic_id: str) -> tuple[SearchEvidence, ...]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        try:
            response = self.client.post(self.endpoint, json={"query": query, "topic_id": topic_id})
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return ()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        evidence: list[SearchEvidence] = []
        for result in results if isinstance(results, list) else []:
            if not isinstance(result, dict):
                continue
            title = str(result.get("title") or "").strip()
            url = str(result.get("url") or "").strip()
            snippet = str(result.get("snippet") or "").strip()
            if not title or not url or not snippet:
                continue
            evidence.append(
                SearchEvidence(
                    topic_id=topic_id, query=query, title=title, url=url,
                    source=str(result.get("source") or "未知来源"),
                    published_at=str(result.get("published_at") or "") or None,
                    snippet=snippet, retrieved_at=retrieved_at,
                    provider=self.provider_name, evidence_status="search_cited",
                )
            )
        return deduplicate_evidence(evidence)


class McpWebSearchProvider:
    """Generic long-lived stdio MCP Web Search provider."""

    def __init__(
        self, *, command: str, args: Sequence[str], env: Mapping[str, str] | None = None,
        tool_name: str = "web_search", provider_name: str = "mcp_web_search",
    ) -> None:
        self.command = command
        self.args = list(args)
        self.env = dict(env or {})
        self.tool_name = tool_name
        self.provider_name = provider_name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready: Future[None] | None = None
        self._session = None
        self._stdio_context = None
        self._session_context = None
        self._stop_event: asyncio.Event | None = None

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready = Future()

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._stop_event = asyncio.Event()
            loop.create_task(self._initialize())
            loop.run_forever()
            loop.close()

        self._thread = threading.Thread(target=runner, name="web-search-mcp", daemon=True)
        self._thread.start()
        self._ready.result(timeout=45)

    async def _initialize(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )
        try:
            self._stdio_context = stdio_client(params)
            read, write = await self._stdio_context.__aenter__()
            self._session_context = ClientSession(read, write)
            self._session = await self._session_context.__aenter__()
            await self._session.initialize()
            self._ready.set_result(None)
            await self._stop_event.wait()
        except Exception as exc:
            if self._ready and not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            if self._session_context:
                await self._session_context.__aexit__(None, None, None)
            if self._stdio_context:
                await self._stdio_context.__aexit__(None, None, None)
            if self._loop:
                self._loop.call_soon(self._loop.stop)

    def close(self) -> None:
        if not self._loop or not self._thread:
            return
        future = asyncio.run_coroutine_threadsafe(self._request_shutdown(), self._loop)
        future.result(timeout=15)
        self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    async def _request_shutdown(self) -> None:
        if self._stop_event:
            self._stop_event.set()

    def __enter__(self) -> "McpWebSearchProvider":
        self._start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query: str, *, topic_id: str) -> tuple[SearchEvidence, ...]:
        self._start()
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(
            self._search(query, topic_id=topic_id), self._loop
        ).result(timeout=60)

    async def _search(self, query: str, *, topic_id: str) -> tuple[SearchEvidence, ...]:
        result = await self._session.call_tool(self.tool_name, {"query": query})
        raw = "\n".join(getattr(item, "text", "") for item in result.content)
        payload = json.loads(raw)
        retrieved_at = datetime.now(timezone.utc).isoformat()
        evidence = []
        result_items = payload.get("organic", payload.get("results", [])) if isinstance(payload, dict) else []
        for item in result_items if isinstance(result_items, list) else []:
            title = str(item.get("title") or "").strip()
            url = str(item.get("link") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if title and url and snippet:
                evidence.append(SearchEvidence(
                    topic_id=topic_id, query=query, title=title, url=url,
                    source=url.split('/')[2], published_at=str(item.get("date") or "") or None,
                    snippet=snippet, retrieved_at=retrieved_at,
                    provider=self.provider_name, evidence_status="search_cited",
                ))
        return deduplicate_evidence(evidence)


class MiniMaxMcpResearchProvider(McpWebSearchProvider):
    """MiniMax Token Plan MCP adapter kept for backwards compatibility."""

    def __init__(self, *, api_key: str, api_host: str = "https://api.minimaxi.com", uvx: str = "uvx") -> None:
        super().__init__(
            command=uvx,
            args=("--with", "fastmcp", "minimax-coding-plan-mcp", "-y"),
            env={"MINIMAX_API_KEY": api_key, "MINIMAX_API_HOST": api_host},
            tool_name="web_search",
            provider_name="minimax_mcp",
        )


def build_web_search_provider() -> ResearchProvider:
    """Build the configured MCP backend without coupling callers to MiniMax."""
    backend = os.getenv("HT_WEB_SEARCH_PROVIDER", "minimax_mcp").strip().lower()
    if backend in {"minimax", "minimax_mcp"}:
        return MiniMaxMcpResearchProvider(
            api_key=os.getenv("MINIMAX_API_KEY", ""),
            api_host=os.getenv("MINIMAX_API_HOST", "https://api.minimaxi.com"),
            uvx=os.getenv("HT_WEB_SEARCH_MCP_COMMAND", "uvx"),
        )
    if backend in {"mcp", "generic_mcp"}:
        raw_args = os.getenv("HT_WEB_SEARCH_MCP_ARGS", "").strip()
        if not raw_args:
            raise ValueError("HT_WEB_SEARCH_MCP_ARGS is required for generic MCP backend")
        raw_env = os.getenv("HT_WEB_SEARCH_MCP_ENV_JSON", "{}").strip()
        parsed_env = json.loads(raw_env)
        if not isinstance(parsed_env, dict):
            raise ValueError("HT_WEB_SEARCH_MCP_ENV_JSON must be a JSON object")
        return McpWebSearchProvider(
            command=os.getenv("HT_WEB_SEARCH_MCP_COMMAND", "").strip(),
            args=shlex.split(raw_args),
            env={str(k): str(v) for k, v in parsed_env.items()},
            tool_name=os.getenv("HT_WEB_SEARCH_MCP_TOOL", "web_search"),
            provider_name=os.getenv("HT_WEB_SEARCH_MCP_PROVIDER_NAME", "mcp_web_search"),
        )
    raise ValueError(f"Unsupported HT_WEB_SEARCH_PROVIDER: {backend}")
