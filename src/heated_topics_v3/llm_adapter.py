"""Provider-neutral OpenAI-compatible LLM adapter shared by daily jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float = 45.0
    reasoning_split: bool = True

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("HT_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
            base_url=os.getenv("HT_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.getenv("HT_LLM_MODEL", "gpt-4o-mini"),
            reasoning_split=os.getenv("HT_LLM_REASONING_SPLIT", "true").lower() in {"1", "true", "yes"},
        )


class LLMAdapter:
    """Small sync adapter for OpenAI-compatible chat completion APIs."""

    def __init__(self, config: LLMConfig | None = None, *, client: httpx.Client | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.client = client or httpx.Client(timeout=self.config.timeout)

    def complete(self, *, system: str, user: str, max_tokens: int = 1600) -> str:
        if not self.config.api_key:
            raise RuntimeError("LLM API key is not configured")
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        if self.config.reasoning_split:
            body["reasoning_split"] = True
        response = self.client.post(
            f"{self.config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
            json=body,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned empty content")
        return content

    async def complete_with_core_memory(self, *, system_instruction: str, user_input: str, max_tokens: int = 1600, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(content=self.complete(system=system_instruction, user=user_input, max_tokens=max_tokens))
