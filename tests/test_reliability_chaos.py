import pytest

from project_mimic.queue_runtime import InMemoryActionQueue, JobStatus
from project_mimic.reliability import (
    BackoffPolicy,
    CircuitBreaker,
    CircuitBreakerConfig,
    TimeoutFailure,
    TransientDependencyError,
    retry_with_backoff,
)


class _Clock:
    def __init__(self, start: float = 2000.0) -> None:
        self.now_value = start

    def now(self) -> float:
        return self.now_value

    def advance(self, seconds: float) -> None:
        self.now_value += seconds


def test_chaos_worker_restart_requeues_and_recovers() -> None:
    clock = _Clock()
    queue = InMemoryActionQueue(now_fn=clock.now)

    job = queue.dispatch({"action": "click"}, idempotency_key="chaos-worker")
    leased = queue.lease_next("worker-a", lease_ttl_seconds=5)
    assert leased is not None
    assert leased.job_id == job.job_id

    # Simulate worker restart by letting the lease expire with no ack/fail.
    clock.advance(6)
    recovered = queue.requeue_expired_leases()
    assert recovered == 1

    takeover = queue.lease_next("worker-b", lease_ttl_seconds=5)
    assert takeover is not None
    assert takeover.job_id == job.job_id

    finished = queue.ack("worker-b", job.job_id)
    assert finished.status == JobStatus.COMPLETED


def test_chaos_timeout_path_opens_circuit_breaker() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=10), now_fn=clock.now)
    policy = BackoffPolicy(base_delay_ms=1, max_delay_ms=2, jitter_ratio=0.0, max_attempts=2)

    def _operation() -> None:
        if not breaker.allow_request():
            raise TimeoutFailure("circuit open due to repeated timeout")
        breaker.record_failure()
        raise TransientDependencyError("dependency timeout")

    with pytest.raises(TransientDependencyError):
        retry_with_backoff(
            _operation,
            policy=policy,
            is_transient=lambda exc: isinstance(exc, TransientDependencyError),
        )

    assert breaker.state.value == "open"
    assert breaker.allow_request() is False
