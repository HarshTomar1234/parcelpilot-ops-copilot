"""Shared provider-failure classification (Phase 4 pre-flight 1C).
Retryable/fallback-eligible failures are transient by nature - a timeout,
a network blip, a 429, a retryable 5xx. Everything else (bad credentials,
a malformed request, an unknown model, insufficient permission, a
response that fails schema validation) is permanent given the same
input - retrying it or falling over to a different provider would either
repeat the identical failure or silently paper over a configuration bug,
so those are classified non-retryable and the caller is expected to stop
immediately rather than keep trying.

Classification is by exception TYPE NAME (duck-typed), not by importing
each provider SDK's exception classes directly - this module must stay
importable without any SDK installed, and the same name convention
(RateLimitError, APIConnectionError, ...) is shared across most current
LLM provider SDKs, so this generalizes past Anthropic specifically.
"""

from __future__ import annotations

RETRYABLE_EXCEPTION_NAMES = frozenset(
    {
        "APIConnectionError",  # network failure
        "APITimeoutError",  # timeout (subclass of APIConnectionError)
        "TimeoutError",  # stdlib / generic timeout
        "ConnectionError",  # stdlib network failure
        "RateLimitError",  # 429
        "InternalServerError",  # 500
        "OverloadedError",  # 529, provider temporarily overloaded
        "ServiceUnavailableError",  # 503
    }
)
# Everything else - AuthenticationError, PermissionDeniedError,
# BadRequestError, NotFoundError, UnprocessableEntityError, ConflictError,
# RequestTooLargeError, APIResponseValidationError (schema failure), and
# any exception this set doesn't name - is non-retryable by default,
# conservative on purpose: retrying or falling back on an error we don't
# recognize could mask a real, permanent configuration problem behind an
# apparent recovery.


def is_retryable_provider_error(exc: Exception) -> bool:
    return type(exc).__name__ in RETRYABLE_EXCEPTION_NAMES
