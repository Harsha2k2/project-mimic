from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.model_registry import JsonFileModelRegistryStore, ModelRegistry


def test_model_registry_register_list_and_promote_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")

    client = TestClient(create_app())

    registered = client.post(
        "/api/v1/models/registry/register",
        headers={"X-API-Key": "admin-key"},
        json={
            "model_id": "planner",
            "version": "v1",
            "artifact_uri": "s3://models/planner/v1",
            "metadata": {"framework": "onnx"},
        },
    )
    assert registered.status_code == 200

    listed = client.get(
        "/api/v1/models/registry/versions",
        headers={"X-API-Key": "admin-key"},
    )
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1

    promoted = client.post(
        "/api/v1/models/registry/channels/canary/promote",
        headers={"X-API-Key": "admin-key"},
        json={"model_id": "planner", "version": "v1"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["assignment"]["channel"] == "canary"

    channels = client.get(
        "/api/v1/models/registry/channels",
        headers={"X-API-Key": "admin-key"},
    )
    assert channels.status_code == 200
    assert channels.json()["channels"]["canary"]["version"] == "v1"


def test_model_registry_rejects_unknown_channel(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")

    client = TestClient(create_app())
    register = client.post(
        "/api/v1/models/registry/register",
        headers={"X-API-Key": "admin-key"},
        json={"model_id": "planner", "version": "v2", "artifact_uri": "s3://models/planner/v2", "metadata": {}},
    )
    assert register.status_code == 200

    response = client.post(
        "/api/v1/models/registry/channels/unknown/promote",
        headers={"X-API-Key": "admin-key"},
        json={"model_id": "planner", "version": "v2"},
    )
    assert response.status_code == 400


def test_model_registry_routes_require_admin(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/models/registry/register",
        headers={"X-API-Key": "viewer-key"},
        json={"model_id": "planner", "version": "v3", "artifact_uri": "s3://models/planner/v3", "metadata": {}},
    )
    assert forbidden.status_code == 403


def test_json_file_model_registry_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "model-registry.json"
    store = JsonFileModelRegistryStore(str(store_path))
    registry = ModelRegistry(store=store)

    registry.register_version(
        model_id="planner",
        version="v4",
        artifact_uri="s3://models/planner/v4",
        metadata={"framework": "triton"},
    )
    registry.promote(channel="dev", model_id="planner", version="v4")

    reloaded = ModelRegistry(store=store)
    versions = reloaded.list_versions(model_id="planner")
    channels = reloaded.list_channels()

    assert len(versions) == 1
    assert versions[0]["version"] == "v4"
    assert channels["dev"] is not None
    assert channels["dev"]["version"] == "v4"
