import pytest

from project_mimic.artifacts import (
    ArtifactManager,
    ArtifactType,
    ArtifactWriteError,
    InMemoryArtifactWriter,
)


class _FailingWriter:
    backend_name = "failing"

    def write_artifact(self, **_kwargs):
        raise RuntimeError("disk unavailable token=abc")

    def read_artifact(self, _record):
        return b""

    def delete_artifact(self, _record):
        return None


def test_artifact_write_uses_fallback_when_primary_fails() -> None:
    manager = ArtifactManager(primary_writer=_FailingWriter(), fallback_writer=InMemoryArtifactWriter())

    record = manager.write(session_id="s1", artifact_type=ArtifactType.TRACE, content=b"trace")
    assert record.metadata["storage_backend"] == "memory"
    assert "fallback_reason" in record.metadata
    assert manager.validate_integrity(record.artifact_id) is True


def test_artifact_write_failure_without_fallback_raises() -> None:
    manager = ArtifactManager(primary_writer=_FailingWriter())

    with pytest.raises(ArtifactWriteError):
        manager.write(session_id="s1", artifact_type=ArtifactType.TRACE, content=b"trace")
