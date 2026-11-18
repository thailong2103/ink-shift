"""Domain exceptions for cloud translation engines."""


class CloudEngineError(Exception):
    """Base exception for all cloud engine failures."""

    def __init__(
        self,
        message: str,
        code: str = "ENGINE_EXECUTION_FAILED",
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class RateLimitExceededError(CloudEngineError):
    """Raised when upstream AI provider rate limits requests (HTTP 429)."""

    def __init__(
        self,
        message: str = "Upstream AI provider rate limit exceeded. Please retry later.",
    ) -> None:
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        )


class ContentSafetyBlockedError(CloudEngineError):
    """Raised when upstream vision model refuses content due to safety policy."""

    def __init__(
        self,
        message: str = "Image was blocked by upstream AI safety filters (sensitive or explicit content). Consider using local-engine.",
    ) -> None:
        super().__init__(
            message=message,
            code="CONTENT_SAFETY_BLOCKED",
            status_code=422,
        )


class UpstreamTimeoutError(CloudEngineError):
    """Raised when upstream API request exceeds timeout threshold."""

    def __init__(
        self,
        message: str = "Upstream AI provider took longer than 15 seconds to respond.",
    ) -> None:
        super().__init__(
            message=message,
            code="UPSTREAM_TIMEOUT",
            status_code=504,
        )


class UpstreamAuthenticationError(CloudEngineError):
    """Raised when API key is missing, invalid, or unauthorized (HTTP 401/403)."""

    def __init__(
        self,
        message: str = "Invalid or missing API key for upstream AI provider.",
    ) -> None:
        super().__init__(
            message=message,
            code="INVALID_API_KEY",
            status_code=401,
        )


class UpstreamExecutionError(CloudEngineError):
    """Raised when upstream provider returns unexpected 5xx or unparseable output."""

    def __init__(
        self,
        message: str = "Upstream AI provider failed to process request.",
    ) -> None:
        super().__init__(
            message=message,
            code="ENGINE_EXECUTION_FAILED",
            status_code=502,
        )
