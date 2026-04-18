"""Artifact storage, indexing, retention, and integrity utilities."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
from pathlib import Path
import threading
import time
from typing import Any, Protocol
from uuid import uuid4


class ArtifactType(str, Enum):
    SCREENSHOT = "screenshot"
    TRACE = "trace"
    LOG = "log"


class ArtifactWriteError(RuntimeError):
    pass


class ArtifactIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    session_id: str
    artifact_type: ArtifactType
    path: str
    checksum_sha256: str
    size_bytes: int
    created_at: float
    metadata: dict[str, str] = field(default_factory=dict)


class ArtifactWriter(Protocol):
    backend_name: str

    def write_artifact(
        self,
        *,
        session_id: str,
        artifact_type: ArtifactType,
        content: bytes,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRecord:
        ...

    def read_artifact(self, record: ArtifactRecord) -> bytes:
        ...

    def delete_artifact(self, record: ArtifactRecord) -> None:
        ...


class ArtifactIndex:
    """In-memory metadata index for fast replay and session lookups."""

    def __init__(self) -> None:
        self._by_id: dict[str, ArtifactRecord] = {}
        self._by_session: dict[str, list[str]] = {}

    def add(self, record: ArtifactRecord) -> None:
        self._by_id[record.artifact_id] = record
        self._by_session.setdefault(record.session_id, []).append(record.artifact_id)

    def get(self, artifact_id: str) -> ArtifactRecord:
        return self._by_id[artifact_id]

    def all(self) -> list[ArtifactRecord]:
        return list(self._by_id.values())

    def remove(self, artifact_id: str) -> None:
        record = self._by_id.pop(artifact_id, None)
        if record is None:
            return

        entries = self._by_session.get(record.session_id, [])
        self._by_session[record.session_id] = [item for item in entries if item != artifact_id]
        if not self._by_session[record.session_id]:
            self._by_session.pop(record.session_id, None)

    def lookup(
        self,
        *,
        session_id: str | None = None,
        artifact_type: ArtifactType | None = None,
        metadata_filters: dict[str, str] | None = None,
    ) -> list[ArtifactRecord]:
        if session_id is None:
            records = self.all()
        else:
            ids = self._by_session.get(session_id, [])
            records = [self._by_id[item] for item in ids if item in self._by_id]

        if artifact_type is not None:
            records = [record for record in records if record.artifact_type == artifact_type]

        if metadata_filters:
            filtered: list[ArtifactRecord] = []
            for record in records:
                if all(record.metadata.get(key) == value for key, value in metadata_filters.items()):
                    filtered.append(record)
            records = filtered

        return records


class FilesystemArtifactWriter:
    backend_name = "filesystem"

    def __init__(self, base_dir: str, *, now_fn=time.time) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn

    def write_artifact(
        self,
        *,
        session_id: str,
        artifact_type: ArtifactType,
        content: bytes,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRecord:
        artifact_id = str(uuid4())
        target_dir = self.base_dir / session_id / artifact_type.value
        target_dir.mkdir(parents=True, exist_ok=True)

        target = target_dir / f"{artifact_id}.bin"
        target.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()
        return ArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            path=str(target),
            checksum_sha256=checksum,
            size_bytes=len(content),
            created_at=self._now(),
            metadata=dict(metadata or {}),
        )

    def read_artifact(self, record: ArtifactRecord) -> bytes:
        return Path(record.path).read_bytes()

    def delete_artifact(self, record: ArtifactRecord) -> None:
        path = Path(record.path)
        if path.exists():
            path.unlink()


class InMemoryArtifactWriter:
    backend_name = "memory"

    def __init__(self, *, now_fn=time.time) -> None:
        self._store: dict[str, bytes] = {}
        self._now = now_fn

    def write_artifact(
        self,
        *,
        session_id: str,
        artifact_type: ArtifactType,
        content: bytes,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRecord:
        artifact_id = str(uuid4())
        self._store[artifact_id] = bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        return ArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            path=f"memory://{artifact_id}",
            checksum_sha256=checksum,
            size_bytes=len(content),
            created_at=self._now(),
            metadata=dict(metadata or {}),
        )

    def read_artifact(self, record: ArtifactRecord) -> bytes:
        return self._store[record.artifact_id]

    def delete_artifact(self, record: ArtifactRecord) -> None:
        self._store.pop(record.artifact_id, None)


@dataclass(frozen=True)
class ArtifactRetentionPolicy:
    max_age_seconds: int
    max_artifacts_per_session: int


class ArtifactManager:
    """Coordinates artifact writes with indexing, fallback, and integrity checks."""

    def __init__(
        self,
        *,
        primary_writer: ArtifactWriter,
        index: ArtifactIndex | None = None,
        fallback_writer: ArtifactWriter | None = None,
        now_fn=time.time,
    ) -> None:
        self.primary_writer = primary_writer
        self.fallback_writer = fallback_writer
        self.index = index or ArtifactIndex()
        self._now = now_fn
        self._writer_by_artifact_id: dict[str, ArtifactWriter] = {}

    def write(
        self,
        *,
        session_id: str,
        artifact_type: ArtifactType,
        content: bytes,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRecord:
        try:
            record = self.primary_writer.write_artifact(
                session_id=session_id,
                artifact_type=artifact_type,
                content=content,
                metadata=metadata,
            )
            record = self._attach_backend(record, self.primary_writer.backend_name)
            self._track(record, self.primary_writer)
            return record
        except Exception as exc:
            if self.fallback_writer is None:
                raise ArtifactWriteError(f"artifact write failed without fallback: {exc}") from exc

            fallback_metadata = dict(metadata or {})
            fallback_metadata["fallback_reason"] = str(exc)
            fallback_record = self.fallback_writer.write_artifact(
                session_id=session_id,
                artifact_type=artifact_type,
                content=content,
                metadata=fallback_metadata,
            )
            fallback_record = self._attach_backend(fallback_record, self.fallback_writer.backend_name)
            self._track(fallback_record, self.fallback_writer)
            return fallback_record

    def register_uploaded_artifact(
        self,
        *,
        session_id: str,
        artifact_type: ArtifactType,
        content: bytes,
        expected_checksum_sha256: str,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRecord:
        checksum = hashlib.sha256(content).hexdigest()
        if checksum != expected_checksum_sha256:
            raise ArtifactIntegrityError("uploaded artifact checksum mismatch")

        return self.write(
            session_id=session_id,
            artifact_type=artifact_type,
            content=content,
            metadata=metadata,
        )

    def validate_integrity(self, artifact_id: str) -> bool:
        record = self.index.get(artifact_id)
        writer = self._writer_by_artifact_id[artifact_id]
        content = writer.read_artifact(record)
        checksum = hashlib.sha256(content).hexdigest()
        return checksum == record.checksum_sha256

    def cleanup(self, retention: ArtifactRetentionPolicy) -> int:
        now = self._now()
        removed = 0

        for record in sorted(self.index.all(), key=lambda item: item.created_at):
            too_old = (now - record.created_at) > retention.max_age_seconds
            if too_old:
                self._delete_record(record)
                removed += 1

        for session_id in list({record.session_id for record in self.index.all()}):
            items = sorted(
                self.index.lookup(session_id=session_id),
                key=lambda item: item.created_at,
                reverse=True,
            )
            for record in items[retention.max_artifacts_per_session :]:
                self._delete_record(record)
                removed += 1

        return removed

    def _delete_record(self, record: ArtifactRecord) -> None:
        writer = self._writer_by_artifact_id.get(record.artifact_id)
        if writer is not None:
            writer.delete_artifact(record)
        self._writer_by_artifact_id.pop(record.artifact_id, None)
        self.index.remove(record.artifact_id)

    def _attach_backend(self, record: ArtifactRecord, backend_name: str) -> ArtifactRecord:
        metadata = dict(record.metadata)
        metadata["storage_backend"] = backend_name
        return replace(record, metadata=metadata)

    def _track(self, record: ArtifactRecord, writer: ArtifactWriter) -> None:
        self.index.add(record)
        self._writer_by_artifact_id[record.artifact_id] = writer


class ArtifactCleanupScheduler:
    """Periodic cleanup scheduler for retention policy enforcement."""

    def __init__(
        self,
        manager: ArtifactManager,
        retention: ArtifactRetentionPolicy,
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        self.manager = manager
        self.retention = retention
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop.wait(self.interval_seconds):
                self.manager.cleanup(self.retention)

        self._thread = threading.Thread(target=_loop, daemon=True, name="artifact-cleanup")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
