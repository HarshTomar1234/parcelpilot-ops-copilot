"""Normalizes every tool call outcome into one typed contract (Phase 3 s8),
so a raw Python exception never becomes the agent protocol. The
orchestrator only ever branches on ToolResult.success/error_type/
retryable - never on catching an exception type itself.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ToolErrorType(StrEnum):
    NOT_FOUND = "not_found"
    NOT_AUTHORIZED = "not_authorized"
    INVALID_ARGUMENTS = "invalid_arguments"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


class ToolResult(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    tool_name: str
    success: bool
    output: T | None = None
    error_type: ToolErrorType | None = None
    retryable: bool = False
    safe_message: str | None = None
    latency_ms: float = 0.0
    attempts: int = 1

    @classmethod
    def ok(cls, tool_name: str, output: T, latency_ms: float, attempts: int = 1) -> ToolResult[T]:
        return cls(
            tool_name=tool_name, success=True, output=output,
            latency_ms=latency_ms, attempts=attempts,
        )

    @classmethod
    def fail(
        cls,
        tool_name: str,
        error_type: ToolErrorType,
        safe_message: str,
        latency_ms: float,
        retryable: bool = False,
        attempts: int = 1,
    ) -> ToolResult[T]:
        return cls(
            tool_name=tool_name,
            success=False,
            error_type=error_type,
            safe_message=safe_message,
            retryable=retryable,
            latency_ms=latency_ms,
            attempts=attempts,
        )
