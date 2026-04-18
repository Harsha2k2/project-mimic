import time

import pytest

from project_mimic.artifacts import (
    ArtifactCleanupScheduler,
    ArtifactIntegrityError,
    ArtifactManager,
    ArtifactRetentionPolicy,
    ArtifactType,
    FilesystemArtifactWriter,
)


def test_artifact_writer_and_index_lookup(tmp_path) -> None:
    manager = ArtifactManager(primary_writer=FilesystemArtifactWriter(str(tmp_path)))

    screenshot = manager.write(
        session_id="s1",
        artifact_type=ArtifactType.SCREENSHOT,
        content=b"img-bytes",
        metadata={"trace_id": "t1"},
    )
    trace = manager.write(
        session_id="s1",
        artifact_type=ArtifactType.TRACE,
        content=b"trace-bytes",
        metadata={"trace_id": "t1"},
    )

    by_session = manager.index.lookup(session_id="s1")
    assert len(by_session) == 2

    traces = manager.index.lookup(
        session_id="s1",
        artifact_type=ArtifactType.TRACE,
        metadata_filters={"trace_id": "t1"},
    )
    assert len(traces) == 1
    assert traces[0].artifact_id == trace.artifact_id
    assert manager.validate_integrity(screenshot.artifact_id) is True


def test_artifact_retention_cleanup_removes_expired(tmp_path) -> None:
    now = [1000.0]

    def _now() -> float:
        return now[0]

    manager = ArtifactManager(
        primary_writer=FilesystemArtifactWriter(str(tmp_path), now_fn=_now),
        now_fn=_now,
    )

    old_record = manager.write(session_id="s1", artifact_type=ArtifactType.LOG, content=b"old")
    now[0] = 1200.0
    manager.write(session_id="s1", artifact_type=ArtifactType.LOG, content=b"new")

    removed = manager.cleanup(ArtifactRetentionPolicy(max_age_seconds=50, max_artifacts_per_session=10))
    assert removed >= 1
    with pytest.raises(KeyError):
        manager.index.get(old_record.artifact_id)


def test_uploaded_artifact_integrity_validation(tmp_path) -> None:
    manager = ArtifactManager(primary_writer=FilesystemArtifactWriter(str(tmp_path)))

    with pytest.raises(ArtifactIntegrityError):
        manager.register_uploaded_artifact(
            session_id="s1",
            artifact_type=ArtifactType.TRACE,
            content=b"payload",
            expected_checksum_sha256="bad-checksum",
        )


def test_retention_enforces_max_artifacts_per_session(tmp_path) -> None:
    manager = ArtifactManager(primary_writer=FilesystemArtifactWriter(str(tmp_path)))
    manager.write(session_id="s1", artifact_type=ArtifactType.LOG, content=b"one")
    time.sleep(0.01)
    manager.write(session_id="s1", artifact_type=ArtifactType.LOG, content=b"two")
    time.sleep(0.01)
    manager.write(session_id="s1", artifact_type=ArtifactType.LOG, content=b"three")

    removed = manager.cleanup(ArtifactRetentionPolicy(max_age_seconds=3600, max_artifacts_per_session=2))
    assert removed == 1
    assert len(manager.index.lookup(session_id="s1")) == 2


def test_cleanup_scheduler_runs_retention_cycle(tmp_path) -> None:
    now = [100.0]

    def _now() -> float:
        return now[0]

    manager = ArtifactManager(
        primary_writer=FilesystemArtifactWriter(str(tmp_path), now_fn=_now),
        now_fn=_now,
    )
    manager.write(session_id="s1", artifact_type=ArtifactType.LOG, content=b"old")

    now[0] = 200.0
    scheduler = ArtifactCleanupScheduler(
        manager,
        ArtifactRetentionPolicy(max_age_seconds=10, max_artifacts_per_session=10),
        interval_seconds=0.01,
    )
    scheduler.start()
    time.sleep(0.05)
    scheduler.stop()

    assert len(manager.index.all()) == 0
