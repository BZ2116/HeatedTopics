"""Custom exception types for the openbiliclaw_integration package."""


class IntegrationError(Exception):
    """Base exception for the integration layer."""


class ProfileValidationError(IntegrationError):
    """Raised when a user profile fails schema validation."""


class CandidateMappingError(IntegrationError):
    """Raised when a V3 Article cannot be mapped to DiscoveredContent."""


class UserPipelineError(IntegrationError):
    """Raised when per-user recommendation pipeline fails.

    Attributes:
        user_id: The user that failed.
        stage: Pipeline stage name (e.g. "fetch", "llm", "timeout").
    """

    def __init__(self, user_id: str, stage: str, message: str) -> None:
        self.user_id = user_id
        self.stage = stage
        super().__init__(f"[{user_id}/{stage}] {message}")


class ProviderFetchError(IntegrationError):
    """Raised when a V3 provider's fetch fails (network, parse, etc.)."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class LLMError(IntegrationError):
    """Raised when the LLM call times out or returns malformed output."""


class EmbeddingDegradedWarning(UserWarning):
    """Issued when embedding service is unavailable; MMR runs in degraded mode."""
