"""Reliability primitives for retries, circuit breaking, and failure taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
import time
from typing import Callable, TypeVar


class FailureCode(str, Enum):
    TRANSIENT_DEPENDENCY = "TRANSIENT_DEPENDENCY"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    CHECKPOINT_RECOVERY = "CHECKPOINT_RECOVERY"
    WORKER_RESTART = "WORKER_RESTART"
    TIMEOUT = "TIMEOUT"


class ProjectMimicFailure(RuntimeError):
    """Base failure for standardized reliability taxonomy."""

    code: FailureCode

    def __init__(self, message: str, *, code: FailureCode) -> None:
        super().__init__(message)
        self.code = code


class TransientDependencyError(ProjectMimicFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=FailureCode.TRANSIENT_DEPENDENCY)


class CircuitOpenError(ProjectMimicFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=FailureCode.CIRCUIT_OPEN)


class CheckpointRecoveryError(ProjectMimicFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=FailureCode.CHECKPOINT_RECOVERY)


class WorkerRestartError(ProjectMimicFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=FailureCode.WORKER_RESTART)


class TimeoutFailure(ProjectMimicFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=FailureCode.TIMEOUT)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 15.0


class CircuitBreaker:
    """Simple circuit breaker with closed/open/half-open transitions."""

    def __init__(self, config: CircuitBreakerConfig | None = None, now_fn=time.time) -> None:
        self.config = config or CircuitBreakerConfig()
        self._now = now_fn
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at: float | None = None

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.opened_at is not None and (self._now() - self.opened_at) >= self.config.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        # half-open allows a probe request
        return True

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.failure_count = self.config.failure_threshold
            self.opened_at = self._now()
            return

        self.failure_count += 1
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = self._now()


@dataclass(frozen=True)
class BackoffPolicy:
    base_delay_ms: int = 100
    max_delay_ms: int = 5000
    jitter_ratio: float = 0.2
    max_attempts: int = 3

    def delay_ms(self, attempt: int, *, deterministic_seed: int | None = None) -> int:
        if attempt < 0:
            raise ValueError("attempt must be non-negative")

        capped = min(self.max_delay_ms, self.base_delay_ms * (2**attempt))
        jitter_span = capped * max(0.0, min(self.jitter_ratio, 1.0))
        rng = random.Random((deterministic_seed or 0) + attempt)
        jittered = capped + rng.uniform(-jitter_span, jitter_span)
        return max(0, int(jittered))


T = TypeVar("T")


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    policy: BackoffPolicy,
    is_transient: Callable[[Exception], bool],
    on_retry: Callable[[int, int, Exception], None] | None = None,
    deterministic_seed: int | None = None,
) -> T:
    last_error: Exception | None = None

    for attempt in range(policy.max_attempts):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            retryable = is_transient(exc)
            if not retryable or attempt >= policy.max_attempts - 1:
                raise

            delay = policy.delay_ms(attempt, deterministic_seed=deterministic_seed)
            if on_retry is not None:
                on_retry(attempt + 1, delay, exc)

    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_with_backoff failed without an error")
