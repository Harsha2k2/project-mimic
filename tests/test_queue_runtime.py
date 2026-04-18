from project_mimic.queue_runtime import InMemoryActionQueue, JobStatus


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now_value = start

    def now(self) -> float:
        return self.now_value

    def advance(self, seconds: float) -> None:
        self.now_value += seconds


def test_idempotency_key_prevents_duplicate_dispatch() -> None:
    queue = InMemoryActionQueue()

    first = queue.dispatch({"action": "click"}, idempotency_key="same-key")
    second = queue.dispatch({"action": "click"}, idempotency_key="same-key")

    assert first.job_id == second.job_id
    assert queue.queue_depth() == 1


def test_worker_lease_heartbeat_and_ack_flow() -> None:
    clock = _Clock()
    queue = InMemoryActionQueue(now_fn=clock.now)

    job = queue.dispatch({"action": "click"}, idempotency_key="lease-1")
    leased = queue.lease_next("worker-a", lease_ttl_seconds=10)
    assert leased is not None
    assert leased.job_id == job.job_id
    assert leased.status == JobStatus.LEASED

    clock.advance(5)
    renewed = queue.renew_lease("worker-a", job.job_id, lease_ttl_seconds=8)
    assert renewed.lease_expires_at == clock.now() + 8

    completed = queue.ack("worker-a", job.job_id)
    assert completed.status == JobStatus.COMPLETED


def test_dead_letter_and_replay_command_flow() -> None:
    clock = _Clock()
    queue = InMemoryActionQueue(now_fn=clock.now)

    job = queue.dispatch({"action": "type"}, idempotency_key="dlq-1")
    job.max_attempts = 2

    first = queue.lease_next("worker-a")
    assert first is not None
    queue.fail("worker-a", job.job_id, reason="temporary error")

    second = queue.lease_next("worker-b")
    assert second is not None
    failed = queue.fail("worker-b", job.job_id, reason="permanent error")
    assert failed.status == JobStatus.DEAD_LETTER
    assert len(queue.list_dead_letter()) == 1

    replayed = queue.replay_dead_letter(job.job_id)
    assert replayed.status == JobStatus.QUEUED
    assert replayed.attempts == 0


def test_recovery_requeues_expired_lease_for_other_worker() -> None:
    clock = _Clock()
    queue = InMemoryActionQueue(now_fn=clock.now)

    job = queue.dispatch({"action": "click"}, idempotency_key="recover-1")

    leased = queue.lease_next("worker-a", lease_ttl_seconds=5)
    assert leased is not None
    assert leased.job_id == job.job_id

    clock.advance(6)
    recovered = queue.requeue_expired_leases()
    assert recovered == 1

    takeover = queue.lease_next("worker-b", lease_ttl_seconds=5)
    assert takeover is not None
    assert takeover.job_id == job.job_id
    assert takeover.status == JobStatus.LEASED

    completed = queue.ack("worker-b", job.job_id)
    assert completed.status == JobStatus.COMPLETED
