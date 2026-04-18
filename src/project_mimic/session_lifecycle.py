"""Session lifecycle management with durability and expiry semantics."""

from __future__ import annotations

import json
from pathlib import Path
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from .environment import ProjectMimicEnv
from .models import Observation, UIAction
from .reliability import CheckpointRecoveryError


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.RUNNING, SessionStatus.EXPIRED, SessionStatus.FAILED},
    SessionStatus.RUNNING: {
        SessionStatus.PAUSED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.EXPIRED,
    },
    SessionStatus.PAUSED: {SessionStatus.RUNNING, SessionStatus.EXPIRED, SessionStatus.FAILED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.FAILED: set(),
    SessionStatus.EXPIRED: set(),
}


class CheckpointStore(Protocol):
    def save(self, session_id: str, payload: dict) -> None:
        ...

    def load(self, session_id: str) -> dict | None:
        ...


class SessionMetadataStore(Protocol):
    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        ...

    def load(self, session_id: str) -> dict[str, Any] | None:
        ...

    def list_all(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def save(self, session_id: str, payload: dict) -> None:
        self._store[session_id] = payload

    def load(self, session_id: str) -> dict | None:
        return self._store.get(session_id)


class InMemorySessionMetadataStore:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        self._store[session_id] = dict(payload)

    def load(self, session_id: str) -> dict[str, Any] | None:
        payload = self._store.get(session_id)
        return dict(payload) if payload is not None else None

    def list_all(self) -> dict[str, dict[str, Any]]:
        return {session_id: dict(payload) for session_id, payload in self._store.items()}


class JsonFileSessionMetadataStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        all_payload = self.list_all()
        all_payload[session_id] = dict(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(all_payload, sort_keys=True), encoding="utf-8")

    def load(self, session_id: str) -> dict[str, Any] | None:
        return self.list_all().get(session_id)

    def list_all(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for session_id, payload in loaded.items():
            if isinstance(session_id, str) and isinstance(payload, dict):
                result[session_id] = dict(payload)
        return result


class RedisCheckpointStore:
    """Redis-backed checkpoint persistence for crash recovery."""

    def __init__(self, redis_url: str, prefix: str = "mimic:checkpoint:") -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis package not installed") from exc

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    def save(self, session_id: str, payload: dict) -> None:
        self._client.set(self._prefix + session_id, json.dumps(payload))

    def load(self, session_id: str) -> dict | None:
        raw = self._client.get(self._prefix + session_id)
        return json.loads(raw) if raw else None


@dataclass
class SessionRecord:
    env: ProjectMimicEnv
    status: SessionStatus
    created_at: float
    last_accessed_at: float
    expires_at: float
    tenant_id: str = "default"


class SessionExpiredError(RuntimeError):
    pass


class InvalidSessionTransitionError(RuntimeError):
    pass


class SessionAccessDeniedError(RuntimeError):
    pass


class SessionRegistry:
    def __init__(
        self,
        ttl_seconds: int = 1800,
        checkpoint_store: CheckpointStore | None = None,
        metadata_store: SessionMetadataStore | None = None,
        now_fn=time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

        self._ttl_seconds = ttl_seconds
        self._checkpoint_store = checkpoint_store or InMemoryCheckpointStore()
        self._metadata_store = metadata_store or InMemorySessionMetadataStore()
        self._records: dict[str, SessionRecord] = {}
        self._now = now_fn

    def create(self, goal: str, max_steps: int, tenant_id: str = "default") -> tuple[str, Observation]:
        session_id = str(uuid4())
        env = ProjectMimicEnv(goal=goal, max_steps=max_steps)
        observation = env.reset()

        now = self._now()
        record = SessionRecord(
            env=env,
            status=SessionStatus.CREATED,
            created_at=now,
            last_accessed_at=now,
            expires_at=now + self._ttl_seconds,
            tenant_id=tenant_id,
        )
        self._records[session_id] = record
        self._transition(record, SessionStatus.RUNNING)
        self._persist_checkpoint(session_id, record)
        return session_id, observation

    def get(self, session_id: str, tenant_id: str | None = None) -> ProjectMimicEnv:
        record = self._records.get(session_id)
        if record is None:
            raise KeyError(session_id)

        self._ensure_tenant_access(record, tenant_id)
        self._ensure_not_expired(record)
        record.last_accessed_at = self._now()
        self._persist_metadata(session_id, record)
        return record.env

    def get_record(self, session_id: str, tenant_id: str | None = None) -> SessionRecord:
        record = self._records.get(session_id)
        if record is None:
            raise KeyError(session_id)

        self._ensure_tenant_access(record, tenant_id)
        self._ensure_not_expired(record)
        return record

    def reset(self, session_id: str, goal: str | None = None, tenant_id: str | None = None) -> Observation:
        record = self.get_record(session_id, tenant_id=tenant_id)
        if record.status in (SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.EXPIRED):
            raise InvalidSessionTransitionError("cannot reset terminal session")

        self._transition(record, SessionStatus.RUNNING)
        observation = record.env.reset(goal=goal)
        record.last_accessed_at = self._now()
        record.expires_at = record.last_accessed_at + self._ttl_seconds
        self._persist_checkpoint(session_id, record)
        return observation

    def restore(self, session_id: str, tenant_id: str | None = None) -> dict:
        payload = self._checkpoint_store.load(session_id)
        if payload is None:
            raise KeyError(session_id)

        checkpoint_tenant = str(payload.get("tenant_id", "default"))
        if tenant_id is not None and checkpoint_tenant != tenant_id:
            raise SessionAccessDeniedError("session does not belong to tenant")
        return payload

    def rollback_to_checkpoint(self, session_id: str, tenant_id: str | None = None) -> dict:
        record = self.get_record(session_id, tenant_id=tenant_id)
        payload = self._checkpoint_store.load(session_id)
        if payload is None:
            raise CheckpointRecoveryError("checkpoint not found")

        state_payload = payload.get("state")
        if not isinstance(state_payload, dict):
            raise CheckpointRecoveryError("checkpoint payload missing state")

        record.env.load_state(state_payload)
        if record.status not in (SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.EXPIRED):
            self._transition(record, SessionStatus.RUNNING)

        record.last_accessed_at = self._now()
        record.expires_at = record.last_accessed_at + self._ttl_seconds
        self._persist_checkpoint(session_id, record)
        return record.env.state()

    def resume_from_checkpoint(self, session_id: str, tenant_id: str | None = None) -> dict:
        return self.rollback_to_checkpoint(session_id, tenant_id=tenant_id)

    def mark_completed(self, session_id: str, tenant_id: str | None = None) -> None:
        record = self.get_record(session_id, tenant_id=tenant_id)
        self._transition(record, SessionStatus.COMPLETED)
        self._persist_checkpoint(session_id, record)

    def mark_failed(self, session_id: str, tenant_id: str | None = None) -> None:
        record = self.get_record(session_id, tenant_id=tenant_id)
        self._transition(record, SessionStatus.FAILED)
        self._persist_checkpoint(session_id, record)

    def pause(self, session_id: str, tenant_id: str | None = None) -> None:
        record = self.get_record(session_id, tenant_id=tenant_id)
        self._transition(record, SessionStatus.PAUSED)
        self._persist_checkpoint(session_id, record)

    def resume(self, session_id: str, tenant_id: str | None = None) -> None:
        record = self.get_record(session_id, tenant_id=tenant_id)
        self._transition(record, SessionStatus.RUNNING)
        self._persist_checkpoint(session_id, record)

    def list_sessions(
        self,
        status: SessionStatus | None = None,
        goal_contains: str | None = None,
        created_after: float | None = None,
        created_before: float | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 50,
        tenant_id: str | None = None,
    ) -> dict:
        if page <= 0 or page_size <= 0:
            raise ValueError("page and page_size must be positive")

        if sort_by not in {"created_at", "last_accessed_at", "expires_at"}:
            raise ValueError("sort_by must be one of created_at,last_accessed_at,expires_at")
        if sort_order not in {"asc", "desc"}:
            raise ValueError("sort_order must be asc or desc")

        items = []
        if self._records:
            for session_id, record in self._records.items():
                if status is not None and record.status != status:
                    continue
                if tenant_id is not None and record.tenant_id != tenant_id:
                    continue

                goal = str(record.env.state().get("goal", ""))
                if goal_contains and goal_contains.lower() not in goal.lower():
                    continue
                if created_after is not None and record.created_at < created_after:
                    continue
                if created_before is not None and record.created_at > created_before:
                    continue

                items.append(
                    {
                        "session_id": session_id,
                        "goal": goal,
                        "status": record.status.value,
                        "created_at": record.created_at,
                        "last_accessed_at": record.last_accessed_at,
                        "expires_at": record.expires_at,
                        "tenant_id": record.tenant_id,
                    }
                )
        else:
            persisted = self._metadata_store.list_all()
            for session_id, payload in persisted.items():
                row_status = str(payload.get("status", SessionStatus.CREATED.value))
                if status is not None and row_status != status.value:
                    continue

                row_tenant_id = str(payload.get("tenant_id", "default"))
                if tenant_id is not None and row_tenant_id != tenant_id:
                    continue

                goal = str(payload.get("goal", ""))
                row_created_at = float(payload.get("created_at", 0.0))
                row_last_accessed_at = float(payload.get("last_accessed_at", row_created_at))
                row_expires_at = float(payload.get("expires_at", row_created_at))

                if goal_contains and goal_contains.lower() not in goal.lower():
                    continue
                if created_after is not None and row_created_at < created_after:
                    continue
                if created_before is not None and row_created_at > created_before:
                    continue

                items.append(
                    {
                        "session_id": session_id,
                        "goal": goal,
                        "status": row_status,
                        "created_at": row_created_at,
                        "last_accessed_at": row_last_accessed_at,
                        "expires_at": row_expires_at,
                        "tenant_id": row_tenant_id,
                    }
                )

        reverse = sort_order == "desc"
        items.sort(key=lambda item: item[sort_by], reverse=reverse)

        start = (page - 1) * page_size
        end = start + page_size
        paged = items[start:end]
        return {
            "items": paged,
            "page": page,
            "page_size": page_size,
            "total": len(items),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "filters": {
                "status": status.value if status else None,
                "goal_contains": goal_contains,
                "created_after": created_after,
                "created_before": created_before,
                "tenant_id": tenant_id,
            },
        }

    def save_checkpoint(self, session_id: str) -> None:
        record = self.get_record(session_id)
        self._persist_checkpoint(session_id, record)

    def scavenge_expired(self) -> int:
        now = self._now()
        expired_count = 0
        for record in self._records.values():
            if record.status in (SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.EXPIRED):
                continue

            if now > record.expires_at:
                self._transition(record, SessionStatus.EXPIRED)
                self._persist_checkpoint(self._session_id_for_record(record), record)
                expired_count += 1
        return expired_count

    def _persist_checkpoint(self, session_id: str, record: SessionRecord) -> None:
        payload = {
            "state": record.env.state(),
            "status": record.status.value,
            "created_at": record.created_at,
            "last_accessed_at": record.last_accessed_at,
            "expires_at": record.expires_at,
            "tenant_id": record.tenant_id,
        }
        self._checkpoint_store.save(session_id, payload)
        self._persist_metadata(session_id, record)

    def _persist_metadata(self, session_id: str, record: SessionRecord) -> None:
        metadata = {
            "goal": str(record.env.state().get("goal", "")),
            "status": record.status.value,
            "created_at": record.created_at,
            "last_accessed_at": record.last_accessed_at,
            "expires_at": record.expires_at,
            "tenant_id": record.tenant_id,
        }
        self._metadata_store.save(session_id, metadata)

    def _session_id_for_record(self, target_record: SessionRecord) -> str:
        for session_id, record in self._records.items():
            if record is target_record:
                return session_id
        raise KeyError("session record not found")

    @staticmethod
    def _transition(record: SessionRecord, target: SessionStatus) -> None:
        allowed = ALLOWED_TRANSITIONS.get(record.status, set())
        if target not in allowed and target != record.status:
            raise InvalidSessionTransitionError(f"{record.status.value} -> {target.value} not allowed")
        record.status = target

    def _ensure_not_expired(self, record: SessionRecord) -> None:
        if self._now() > record.expires_at:
            self._transition(record, SessionStatus.EXPIRED)
            raise SessionExpiredError("session expired")

    @staticmethod
    def _ensure_tenant_access(record: SessionRecord, tenant_id: str | None) -> None:
        if tenant_id is None:
            return
        if record.tenant_id != tenant_id:
            raise SessionAccessDeniedError("session does not belong to tenant")
