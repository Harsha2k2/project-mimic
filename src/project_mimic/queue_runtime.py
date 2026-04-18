"""In-memory queue and worker lease runtime for task dispatch orchestration."""

from __future__ import annotations

from collections import deque
from enum import Enum
import time
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field

from .models import ProjectMimicModel


class JobStatus(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class ActionJob(ProjectMimicModel):
    job_id: str
    idempotency_key: str
    action_payload: dict[str, Any]
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    max_attempts: int = Field(default=3, ge=1)
    created_at: float
    updated_at: float
    lease_worker_id: str | None = None
    lease_expires_at: float | None = None
    last_error: str | None = None


class WorkerLease(ProjectMimicModel):
    worker_id: str
    job_id: str
    lease_expires_at: float
    heartbeat_at: float


class ActionQueue(Protocol):
    def dispatch(self, action_payload: dict[str, Any], *, idempotency_key: str) -> ActionJob:
        ...

    def lease_next(self, worker_id: str, *, lease_ttl_seconds: int = 30) -> ActionJob | None:
        ...

    def renew_lease(self, worker_id: str, job_id: str, *, lease_ttl_seconds: int = 30) -> WorkerLease:
        ...

    def ack(self, worker_id: str, job_id: str) -> ActionJob:
        ...

    def fail(self, worker_id: str, job_id: str, *, reason: str) -> ActionJob:
        ...

    def replay_dead_letter(self, job_id: str) -> ActionJob:
        ...


class InMemoryActionQueue:
    """Queue runtime with worker leases, dead-lettering, and replay support."""

    def __init__(self, now_fn=time.time) -> None:
        self._now = now_fn
        self._jobs: dict[str, ActionJob] = {}
        self._idempotency: dict[str, str] = {}
        self._ready: deque[str] = deque()
        self._dead_letter: deque[str] = deque()
        self._leases: dict[str, WorkerLease] = {}

    def dispatch(self, action_payload: dict[str, Any], *, idempotency_key: str) -> ActionJob:
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key is required")

        existing_job_id = self._idempotency.get(key)
        if existing_job_id:
            return self._jobs[existing_job_id]

        now = self._now()
        job = ActionJob(
            job_id=str(uuid4()),
            idempotency_key=key,
            action_payload=dict(action_payload),
            status=JobStatus.QUEUED,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.job_id] = job
        self._idempotency[key] = job.job_id
        self._ready.append(job.job_id)
        return job

    def lease_next(self, worker_id: str, *, lease_ttl_seconds: int = 30) -> ActionJob | None:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")

        self.requeue_expired_leases()

        while self._ready:
            job_id = self._ready.popleft()
            job = self._jobs[job_id]
            if job.status != JobStatus.QUEUED:
                continue

            now = self._now()
            expires_at = now + lease_ttl_seconds
            job.status = JobStatus.LEASED
            job.attempts += 1
            job.lease_worker_id = worker_id
            job.lease_expires_at = expires_at
            job.updated_at = now

            self._leases[job.job_id] = WorkerLease(
                worker_id=worker_id,
                job_id=job.job_id,
                lease_expires_at=expires_at,
                heartbeat_at=now,
            )
            return job

        return None

    def renew_lease(self, worker_id: str, job_id: str, *, lease_ttl_seconds: int = 30) -> WorkerLease:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")

        lease = self._leases.get(job_id)
        if lease is None:
            raise ValueError("lease not found")
        if lease.worker_id != worker_id:
            raise ValueError("lease belongs to a different worker")

        now = self._now()
        if lease.lease_expires_at < now:
            raise ValueError("lease already expired")

        updated = WorkerLease(
            worker_id=worker_id,
            job_id=job_id,
            lease_expires_at=now + lease_ttl_seconds,
            heartbeat_at=now,
        )
        self._leases[job_id] = updated

        job = self._jobs[job_id]
        job.lease_expires_at = updated.lease_expires_at
        job.updated_at = now
        return updated

    def ack(self, worker_id: str, job_id: str) -> ActionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)

        lease = self._leases.get(job_id)
        if lease is None or lease.worker_id != worker_id:
            raise ValueError("worker does not hold lease")

        now = self._now()
        job.status = JobStatus.COMPLETED
        job.lease_worker_id = None
        job.lease_expires_at = None
        job.updated_at = now
        self._leases.pop(job_id, None)
        return job

    def fail(self, worker_id: str, job_id: str, *, reason: str) -> ActionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)

        lease = self._leases.get(job_id)
        if lease is None or lease.worker_id != worker_id:
            raise ValueError("worker does not hold lease")

        now = self._now()
        job.last_error = reason
        job.lease_worker_id = None
        job.lease_expires_at = None
        job.updated_at = now
        self._leases.pop(job_id, None)

        if job.attempts >= job.max_attempts:
            job.status = JobStatus.DEAD_LETTER
            self._dead_letter.append(job_id)
        else:
            job.status = JobStatus.QUEUED
            self._ready.append(job_id)

        return job

    def replay_dead_letter(self, job_id: str) -> ActionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status != JobStatus.DEAD_LETTER:
            raise ValueError("job is not in dead letter queue")

        now = self._now()
        job.status = JobStatus.QUEUED
        job.attempts = 0
        job.updated_at = now
        job.last_error = None

        try:
            self._dead_letter.remove(job_id)
        except ValueError:
            pass
        self._ready.append(job_id)
        return job

    def requeue_expired_leases(self) -> int:
        now = self._now()
        expired: list[str] = []
        for job_id, lease in self._leases.items():
            if lease.lease_expires_at < now:
                expired.append(job_id)

        recovered = 0
        for job_id in expired:
            self._leases.pop(job_id, None)
            job = self._jobs[job_id]
            job.lease_worker_id = None
            job.lease_expires_at = None
            job.updated_at = now

            if job.attempts >= job.max_attempts:
                job.status = JobStatus.DEAD_LETTER
                self._dead_letter.append(job_id)
            else:
                job.status = JobStatus.QUEUED
                self._ready.append(job_id)
            recovered += 1
        return recovered

    def get_job(self, job_id: str) -> ActionJob:
        return self._jobs[job_id]

    def list_dead_letter(self) -> list[ActionJob]:
        return [self._jobs[job_id] for job_id in self._dead_letter]

    def queue_depth(self) -> int:
        return len([job_id for job_id in self._ready if self._jobs[job_id].status == JobStatus.QUEUED])
