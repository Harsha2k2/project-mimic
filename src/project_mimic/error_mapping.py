"""Error code mapping helpers for model and API contract failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .models import ErrorCode


@dataclass(frozen=True)
class ErrorEnvelope:
    code: ErrorCode
    message: str
    details: list[dict[str, Any]]


def map_exception_to_error(exc: Exception) -> ErrorEnvelope:
    if isinstance(exc, ValidationError):
        return ErrorEnvelope(
            code=ErrorCode.VALIDATION_ERROR,
            message="payload validation failed",
            details=exc.errors(),
        )

    if isinstance(exc, ValueError):
        return ErrorEnvelope(
            code=ErrorCode.PAYLOAD_CONSTRAINT_VIOLATION,
            message=str(exc),
            details=[],
        )

    return ErrorEnvelope(
        code=ErrorCode.SERIALIZATION_ERROR,
        message=str(exc),
        details=[],
    )
