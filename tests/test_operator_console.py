import base64
from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_operator_console_renders_live_dashboard(monkeypatch, tmp_path) -> None:
    artifacts_path = tmp_path / "artifacts.json"
    artifacts_path.write_text('{"items": [{"artifact_id": "a1", "session_id": "s1"}]}', encoding="utf-8")
    queue_path = tmp_path / "queue.json"
    queue_path.write_text('{"jobs": {"j1": {}}, "ready": ["j1"], "dead_letter": [], "leases": {}}', encoding="utf-8")
    monkeypatch.setenv("OPERATOR_CONSOLE_ARTIFACTS_FILE_PATH", str(artifacts_path))
    monkeypatch.setenv("OPERATOR_CONSOLE_QUEUE_FILE_PATH", str(queue_path))
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    client = TestClient(create_app())

    response = client.get("/api/v1/operator", headers={"X-API-Key": "admin-key"})
    assert response.status_code == 200
    assert "Project Mimic Operator Console" in response.text
    assert "Sessions" in response.text
    assert "Traces" in response.text
    assert "Artifacts" in response.text
    assert "Screenshot Artifacts" in response.text
    assert "Queue State" in response.text


def test_operator_console_snapshot_requires_admin(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")
    client = TestClient(create_app())

    denied = client.get("/api/v1/operator/snapshot", headers={"X-API-Key": "viewer-key"})
    assert denied.status_code == 403

    allowed = client.get("/api/v1/operator/snapshot", headers={"X-API-Key": "admin-key"})
    assert allowed.status_code == 200
    payload = allowed.json()
    assert "sessions" in payload
    assert "traces" in payload
    assert "live_artifacts" in payload


def test_operator_console_includes_screenshot_artifact_links(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "admin-key"},
        json={"goal": "artifact-console", "max_steps": 1},
    )
    session_id = created.json()["session_id"]
    upload = client.post(
        f"/api/v1/sessions/{session_id}/artifacts/screenshot",
        headers={"X-API-Key": "admin-key"},
        json={"screenshot_base64": base64.b64encode(b"artifact-bytes").decode("ascii")},
    )
    artifact_id = upload.json()["artifact_id"]

    response = client.get("/api/v1/operator", headers={"X-API-Key": "admin-key"})
    assert response.status_code == 200
    assert f"/api/v1/artifacts/{artifact_id}/content" in response.text