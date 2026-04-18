import pytest

from project_mimic.reliability import (
    BackoffPolicy,
    CheckpointRecoveryError,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    FailureCode,
    TransientDependencyError,
    WorkerRestartError,
    retry_with_backoff,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now_value = start

    def now(self) -> float:
        return self.now_value

    def advance(self, seconds: float) -> None:
        self.now_value += seconds


def test_backoff_policy_exponential_jitter_bounds() -> None:
    policy = BackoffPolicy(base_delay_ms=100, max_delay_ms=2000, jitter_ratio=0.2, max_attempts=4)

    delays = [policy.delay_ms(attempt, deterministic_seed=7) for attempt in range(4)]
    assert delays[0] >= 80
    assert delays[1] >= 160
    assert delays[2] >= 320
    assert delays[3] <= 2000


def test_circuit_breaker_open_half_open_closed_transitions() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=5), now_fn=clock.now)

    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.state.value == "closed"

    breaker.record_failure()
    assert breaker.state.value == "open"
    assert breaker.allow_request() is False

    clock.advance(6)
    assert breaker.allow_request() is True
    assert breaker.state.value == "half_open"

    breaker.record_success()
    assert breaker.state.value == "closed"


def test_retry_with_backoff_retries_transient_error_until_success() -> None:
    policy = BackoffPolicy(base_delay_ms=10, max_delay_ms=40, jitter_ratio=0.0, max_attempts=3)
    attempts = {"count": 0}
    seen_delays: list[int] = []

    def _operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientDependencyError("transient")
        return "ok"

    result = retry_with_backoff(
        _operation,
        policy=policy,
        is_transient=lambda exc: isinstance(exc, TransientDependencyError),
        on_retry=lambda _attempt, delay, _exc: seen_delays.append(delay),
        deterministic_seed=1,
    )
    assert result == "ok"
    assert attempts["count"] == 3
    assert seen_delays


def test_failure_taxonomy_error_codes_are_stable() -> None:
    assert TransientDependencyError("x").code == FailureCode.TRANSIENT_DEPENDENCY
    assert CircuitOpenError("x").code == FailureCode.CIRCUIT_OPEN
    assert CheckpointRecoveryError("x").code == FailureCode.CHECKPOINT_RECOVERY
    assert WorkerRestartError("x").code == FailureCode.WORKER_RESTART


def test_retry_with_backoff_stops_on_non_transient_error() -> None:
    policy = BackoffPolicy(max_attempts=3)

    def _operation() -> None:
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        retry_with_backoff(
            _operation,
            policy=policy,
            is_transient=lambda exc: isinstance(exc, TransientDependencyError),
        )
