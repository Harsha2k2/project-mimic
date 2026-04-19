from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.status_portal import CustomerStatusPortalService, JsonFileStatusPortalStore


def test_status_portal_service_and_sla_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key,viewer-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator,viewer-key:viewer")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a,viewer-key:tenant-a")

    client = TestClient(create_app())

    status = client.post(
        "/api/v1/status/services/control-plane",
        headers={"X-API-Key": "admin-key"},
        json={
            "display_name": "Control Plane",
            "status": "operational",
            "availability_percent": 99.95,
            "latency_p95_ms": 120.0,
            "error_rate_percent": 0.2,
            "components": {"api": "operational", "queue": "operational"},
            "message": "Healthy",
        },
    )
    assert status.status_code == 200

    target = client.post(
        "/api/v1/status/sla/control-plane",
        headers={"X-API-Key": "admin-key"},
        json={
            "availability_target_percent": 99.9,
            "latency_p95_target_ms": 200.0,
            "error_rate_target_percent": 1.0,
            "window_days": 30,
        },
    )
    assert target.status_code == 200

    listing = client.get(
        "/api/v1/status/services",
        headers={"X-API-Key": "viewer-key"},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    evaluate = client.get(
        "/api/v1/status/sla/control-plane/evaluate",
        headers={"X-API-Key": "operator-key"},
    )
    assert evaluate.status_code == 200
    payload = evaluate.json()
    assert payload["service_id"] == "control-plane"
    assert payload["meets_sla"] is True
    assert payload["violations"] == []


def test_status_portal_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key,viewer-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator,viewer-key:viewer")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a,viewer-key:tenant-a")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/status/services/control-plane",
        headers={"X-API-Key": "operator-key"},
        json={
            "display_name": "Control Plane",
            "status": "operational",
            "availability_percent": 99.95,
            "latency_p95_ms": 120.0,
            "error_rate_percent": 0.2,
            "components": {},
            "message": "ok",
        },
    )
    assert forbidden.status_code == 403

    seed_status = client.post(
        "/api/v1/status/services/control-plane",
        headers={"X-API-Key": "admin-key"},
        json={
            "display_name": "Control Plane",
            "status": "degraded",
            "availability_percent": 98.0,
            "latency_p95_ms": 450.0,
            "error_rate_percent": 2.5,
            "components": {"api": "degraded"},
            "message": "investigating",
        },
    )
    assert seed_status.status_code == 200

    seed_target = client.post(
        "/api/v1/status/sla/control-plane",
        headers={"X-API-Key": "admin-key"},
        json={
            "availability_target_percent": 99.0,
            "latency_p95_target_ms": 200.0,
            "error_rate_target_percent": 1.0,
            "window_days": 30,
        },
    )
    assert seed_target.status_code == 200

    legacy_eval = client.get(
        "/status/sla/control-plane/evaluate",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_eval.status_code == 200
    assert legacy_eval.headers.get("Deprecation") == "true"
    assert legacy_eval.json()["meets_sla"] is False
    assert set(legacy_eval.json()["violations"]) == {"availability", "latency_p95", "error_rate"}


def test_json_file_status_portal_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "status-portal.json"
    service = CustomerStatusPortalService(store=JsonFileStatusPortalStore(str(store_path)))

    service.upsert_service_status(
        service_id="control-plane",
        display_name="Control Plane",
        status="operational",
        availability_percent=99.95,
        latency_p95_ms=100.0,
        error_rate_percent=0.1,
        components={"api": "operational"},
        message="ok",
    )
    service.upsert_sla_target(
        service_id="control-plane",
        availability_target_percent=99.9,
        latency_p95_target_ms=200.0,
        error_rate_target_percent=1.0,
        window_days=30,
    )

    evaluation = service.evaluate_sla(service_id="control-plane")
    assert evaluation["meets_sla"] is True

    reloaded = CustomerStatusPortalService(store=JsonFileStatusPortalStore(str(store_path)))
    statuses = reloaded.list_service_statuses()
    targets = reloaded.list_sla_targets()

    assert len(statuses) == 1
    assert len(targets) == 1
