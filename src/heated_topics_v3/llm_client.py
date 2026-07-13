"""LLM HTTP client for Anthropic-format chat completions.

Reads API key/base_url/model from env (MINIMAX_* with ANTHROPIC_* fallback).
Caches responses on disk by sha256(model+system+prompt).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class LLMUnavailable(RuntimeError):
    """Raised when the LLM API is unreachable, returns no text, or the key is missing."""


DEFAULT_BASE_URL = "https://api.minimaxi.com/anthropic"
DEFAULT_MODEL = "MiniMax-Text-01"
DEFAULT_CACHE_DIR = "cache/llm"


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


def load_llm_config() -> LLMConfig:
    """Read LLM config from env. Prefers MINIMAX_*, falls back to ANTHROPIC_*."""
    api_key = (
        os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    base_url = (
        os.environ.get("MINIMAX_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    model = (
        os.environ.get("MINIMAX_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or DEFAULT_MODEL
    ).strip()
    return LLMConfig(api_key=api_key, base_url=base_url, model=model)


def llm_cache_path(cache_dir: str | Path, prompt: str, system: str | None, model: str) -> Path:
    payload = json.dumps(
        {"model": model, "system": system or "", "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return Path(cache_dir) / f"{digest}.json"


def strip_code_fence(text: str) -> str:
    """Remove leading/trailing ```json ... ``` fences if present."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def call_llm(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    use_cache: bool = True,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    config: LLMConfig | None = None,
    user_agent: str = "HeatedTopics-V3/0.1",
    timeout_seconds: int = 60,
) -> str:
    """Call an Anthropic-format chat completion. Returns the assistant text.

    Raises LLMUnavailable on missing key, HTTP error, or empty response.
    """
    cfg = config or load_llm_config()
    if not cfg.is_configured:
        raise LLMUnavailable("LLM API key not set (MINIMAX_API_KEY or ANTHROPIC_AUTH_TOKEN)")

    cache_path = llm_cache_path(cache_dir, prompt, system, cfg.model)
    if use_cache:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cached_text = cached.get("text")
                if isinstance(cached_text, str) and cached_text:
                    return cached_text
            except (json.JSONDecodeError, OSError):
                pass

    body = {
        "model": cfg.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    request = urllib.request.Request(
        f"{cfg.base_url}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": user_agent,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise LLMUnavailable(f"LLM call failed: {exc}") from exc

    parts = payload.get("content") or []
    text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
    if not text:
        raise LLMUnavailable(f"LLM returned no text: {payload}")

    if use_cache:
        try:
            cache_path.write_text(
                json.dumps(
                    {"model": cfg.model, "system": system or "", "prompt": prompt, "text": text},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
    return text