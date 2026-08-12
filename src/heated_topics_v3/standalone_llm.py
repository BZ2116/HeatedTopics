"""Backward-compatible names for the shared LLM adapter."""

from .llm_adapter import LLMAdapter, LLMConfig

StandaloneLLMClient = LLMAdapter

__all__ = ["LLMAdapter", "LLMConfig", "StandaloneLLMClient"]
