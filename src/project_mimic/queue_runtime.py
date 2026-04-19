"""In-memory queue and worker lease runtime for task dispatch orchestration."""

from __future__ import annotations

from collections import deque
from enum import Enum
import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field

from .models import ProjectMimicModel


class JobStatus(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    CANCELED = "canceled"
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

    def cancel(self, job_id: str, *, reason: str) -> ActionJob:
        ...

    def quarantine(self, job_id: str, *, reason: str) -> ActionJob:
        ...


class QueueStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any] | None:
        ...


class InMemoryQueueStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] | None = None

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = dict(payload)

    def load(self) -> dict[str, Any] | None:
        return dict(self._payload) if self._payload is not None else None


class JsonFileQueueStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        loaded = json.loads(content)
        return loaded if isinstance(loaded, dict) else None


class InMemoryActionQueue:
    """Queue runtime with worker leases, dead-lettering, and replay support."""

    def __init__(
        self,
        now_fn=time.time,
        store: QueueStore | None = None,
        idempotency_ttl_seconds: int = 3600,
    ) -> None:
        self._now = now_fn
        self._store = store or InMemoryQueueStore()
        if idempotency_ttl_seconds <= 0:
            raise ValueError("idempotency_ttl_seconds must be positive")
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._jobs: dict[str, ActionJob] = {}
        self._idempotency: dict[str, str] = {}
        self._idempotency_expires: dict[str, float] = {}
        self._ready: deque[str] = deque()
        self._dead_letter: deque[str] = deque()
        self._leases: dict[str, WorkerLease] = {}
        self._restore_from_store()

    def dispatch(self, action_payload: dict[str, Any], *, idempotency_key: str) -> ActionJob:
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key is required")

        self._cleanup_expired_idempotency()

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
        self._idempotency_expires[key] = now + self._idempotency_ttl_seconds
        self._ready.append(job.job_id)
        self._persist_state()
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
            self._persist_state()
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
        self._persist_state()
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
        self._persist_state()
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

        self._persist_state()
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
        self._persist_state()
        return job

    def cancel(self, job_id: str, *, reason: str) -> ActionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)

        reason_text = reason.strip()
        if not reason_text:
            raise ValueError("reason is required")

        if job.status in {JobStatus.COMPLETED, JobStatus.DEAD_LETTER, JobStatus.CANCELED}:
            raise ValueError("job is already terminal")

        now = self._now()
        job.status = JobStatus.CANCELED
        job.last_error = reason_text
        job.lease_worker_id = None
        job.lease_expires_at = None
        job.updated_at = now

        self._leases.pop(job_id, None)
        self._ready = deque(queued_job_id for queued_job_id in self._ready if queued_job_id != job_id)
        self._persist_state()
        return job

    def quarantine(self, job_id: str, *, reason: str) -> ActionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)

        reason_text = reason.strip()
        if not reason_text:
            raise ValueError("reason is required")

        if job.status == JobStatus.COMPLETED:
            raise ValueError("cannot quarantine completed job")

        now = self._now()
        job.status = JobStatus.DEAD_LETTER
        job.last_error = reason_text
        job.lease_worker_id = None
        job.lease_expires_at = None
        job.updated_at = now

        self._leases.pop(job_id, None)
        self._ready = deque(queued_job_id for queued_job_id in self._ready if queued_job_id != job_id)
        if job_id not in self._dead_letter:
            self._dead_letter.append(job_id)

        self._persist_state()
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
        if recovered:
            self._persist_state()
        return recovered

    def get_job(self, job_id: str) -> ActionJob:
        return self._jobs[job_id]

    def list_dead_letter(self) -> list[ActionJob]:
        return [self._jobs[job_id] for job_id in self._dead_letter]

    def queue_depth(self) -> int:
        return len([job_id for job_id in self._ready if self._jobs[job_id].status == JobStatus.QUEUED])

    def _persist_state(self) -> None:
        payload = {
            "jobs": {job_id: job.model_dump(mode="json") for job_id, job in self._jobs.items()},
            "idempotency": dict(self._idempotency),
            "idempotency_expires": dict(self._idempotency_expires),
            "ready": list(self._ready),
            "dead_letter": list(self._dead_letter),
            "leases": {job_id: lease.model_dump(mode="json") for job_id, lease in self._leases.items()},
        }
        self._store.save(payload)

    def _restore_from_store(self) -> None:
        payload = self._store.load()
        if not payload:
            return

        jobs_payload = payload.get("jobs", {})
        idempotency_payload = payload.get("idempotency", {})
        idempotency_expires_payload = payload.get("idempotency_expires", {})
        ready_payload = payload.get("ready", [])
        dead_letter_payload = payload.get("dead_letter", [])
        leases_payload = payload.get("leases", {})

        if isinstance(jobs_payload, dict):
            for job_id, data in jobs_payload.items():
                if isinstance(job_id, str) and isinstance(data, dict):
                    self._jobs[job_id] = ActionJob(**data)

        if isinstance(idempotency_payload, dict):
            self._idempotency = {
                str(key): str(value)
                for key, value in idempotency_payload.items()
                if isinstance(key, str) and isinstance(value, str)
            }

        if isinstance(idempotency_expires_payload, dict):
            self._idempotency_expires = {
                str(key): float(value)
                for key, value in idempotency_expires_payload.items()
                if isinstance(key, str)
            }

        self._cleanup_expired_idempotency()

        if isinstance(ready_payload, list):
            self._ready = deque(
                job_id
                for job_id in ready_payload
                if isinstance(job_id, str) and job_id in self._jobs
            )

        if isinstance(dead_letter_payload, list):
            self._dead_letter = deque(
                job_id
                for job_id in dead_letter_payload
                if isinstance(job_id, str) and job_id in self._jobs
            )

        if isinstance(leases_payload, dict):
            for job_id, data in leases_payload.items():
                if isinstance(job_id, str) and isinstance(data, dict) and job_id in self._jobs:
                    self._leases[job_id] = WorkerLease(**data)

    def _cleanup_expired_idempotency(self) -> None:
        now = self._now()
        expired_keys = [key for key, expires_at in self._idempotency_expires.items() if expires_at <= now]
        for key in expired_keys:
            self._idempotency_expires.pop(key, None)
            self._idempotency.pop(key, None)
