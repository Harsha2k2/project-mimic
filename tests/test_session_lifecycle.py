import pytest

from project_mimic.models import ActionType, UIAction
from project_mimic.session_lifecycle import (
    InMemoryCheckpointStore,
    InvalidSessionTransitionError,
    JsonFileSessionMetadataStore,
    SessionExpiredError,
    SessionRegistry,
    SessionStatus,
)


def test_session_expiration_and_scavenge() -> None:
    now = [100.0]

    def _now() -> float:
        return now[0]

    registry = SessionRegistry(ttl_seconds=10, now_fn=_now)
    session_id, _ = registry.create(goal="g", max_steps=5)

    now[0] = 111.0
    expired = registry.scavenge_expired()
    assert expired == 1

    with pytest.raises(SessionExpiredError):
        registry.get(session_id)


def test_checkpoint_restore_after_step() -> None:
    store = InMemoryCheckpointStore()
    registry = SessionRegistry(ttl_seconds=100, checkpoint_store=store)

    session_id, _ = registry.create(goal="g", max_steps=3)
    env = registry.get(session_id)
    env.step(UIAction(action_type=ActionType.CLICK, target="search"))
    registry.save_checkpoint(session_id)

    payload = registry.restore(session_id)
    assert payload["state"]["step_index"] == 1
    assert payload["status"] in {"running", "completed"}


def test_reset_disallowed_for_terminal_session() -> None:
    registry = SessionRegistry(ttl_seconds=100)
    session_id, _ = registry.create(goal="g", max_steps=2)
    registry.mark_completed(session_id)

    with pytest.raises(InvalidSessionTransitionError):
        registry.reset(session_id)


def test_rollback_and_resume_restore_checkpoint_state() -> None:
    store = InMemoryCheckpointStore()
    registry = SessionRegistry(ttl_seconds=100, checkpoint_store=store)

    session_id, _ = registry.create(goal="rollback-goal", max_steps=4)
    env = registry.get(session_id)
    env.step(UIAction(action_type=ActionType.CLICK, target="search"))
    registry.save_checkpoint(session_id)

    env.step(UIAction(action_type=ActionType.CLICK, target="offer"))
    state_before = env.state()
    assert state_before["step_index"] == 2

    rolled_back = registry.rollback_to_checkpoint(session_id)
    assert rolled_back["step_index"] == 1

    resumed = registry.resume_from_checkpoint(session_id)
    assert resumed["step_index"] == 1


def test_json_metadata_store_persists_session_listing_across_registry_restart(tmp_path) -> None:
    metadata_file = tmp_path / "session-metadata.json"
    metadata_store = JsonFileSessionMetadataStore(str(metadata_file))

    registry = SessionRegistry(ttl_seconds=100, metadata_store=metadata_store)
    session_id, _ = registry.create(goal="persisted-goal", max_steps=2, tenant_id="tenant-a")

    listing_before = registry.list_sessions(tenant_id="tenant-a")
    assert any(item["session_id"] == session_id for item in listing_before["items"])

    reloaded_registry = SessionRegistry(ttl_seconds=100, metadata_store=metadata_store)
    listing_after = reloaded_registry.list_sessions(tenant_id="tenant-a")
    assert any(item["session_id"] == session_id for item in listing_after["items"])


def test_json_metadata_store_tracks_status_transitions(tmp_path) -> None:
    metadata_file = tmp_path / "session-metadata.json"
    metadata_store = JsonFileSessionMetadataStore(str(metadata_file))

    registry = SessionRegistry(ttl_seconds=100, metadata_store=metadata_store)
    session_id, _ = registry.create(goal="status-goal", max_steps=1, tenant_id="tenant-a")
    registry.mark_completed(session_id, tenant_id="tenant-a")

    reloaded_registry = SessionRegistry(ttl_seconds=100, metadata_store=metadata_store)
    listing = reloaded_registry.list_sessions(status=SessionStatus.COMPLETED, tenant_id="tenant-a")
    assert any(item["session_id"] == session_id for item in listing["items"])
