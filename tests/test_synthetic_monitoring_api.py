from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.synthetic_monitoring import SyntheticMonitor
from project_mimic.testing.ephemeral_services import ephemeral_integration_environment


def test_synthetic_monitor_reports_healthy_when_all_probes_pass() -> None:
    monitor = SyntheticMonitor(
        api_probe=lambda: None,
        worker_probe=lambda: None,
        triton_client=None,
        triton_endpoint="",
    )

    report = monitor.run_all()

    assert report["overall_healthy"] is False
    assert report["checks"]["inference"]["ok"] is False


def test_synthetic_monitoring_endpoint_returns_report_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    monkeypatch.setenv("SYNTHETIC_MONITORING_ENABLED", "true")

    with ephemeral_integration_environment() as env:
        monkeypatch.setenv("SYNTHETIC_MONITORING_TRITON_ENDPOINT", env.triton_endpoint)
        monkeypatch.setenv("SYNTHETIC_MONITORING_TRITON_MODEL", "ui-detector")

        client = TestClient(create_app())
        response = client.get("/api/v1/monitoring/synthetic", headers={"X-API-Key": "admin-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_healthy"] is True
    assert payload["checks"]["api"]["ok"] is True
    assert payload["checks"]["queue"]["ok"] is True
    assert payload["checks"]["worker"]["ok"] is True
    assert payload["checks"]["inference"]["ok"] is True
    assert payload["checks"]["inference"]["entities"] >= 1


def test_synthetic_monitoring_endpoint_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")

    client = TestClient(create_app())
    response = client.get("/api/v1/monitoring/synthetic", headers={"X-API-Key": "admin-key"})

    assert response.status_code == 404


def test_synthetic_monitoring_legacy_route_sets_deprecation_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    monkeypatch.setenv("SYNTHETIC_MONITORING_ENABLED", "true")

    with ephemeral_integration_environment() as env:
        monkeypatch.setenv("SYNTHETIC_MONITORING_TRITON_ENDPOINT", env.triton_endpoint)
        monkeypatch.setenv("SYNTHETIC_MONITORING_TRITON_MODEL", "ui-detector")

        client = TestClient(create_app())
        response = client.get("/monitoring/synthetic", headers={"X-API-Key": "admin-key"})

    assert response.status_code == 200
    assert response.headers.get("Deprecation") == "true"


def test_synthetic_monitoring_routes_require_admin(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")
    monkeypatch.setenv("SYNTHETIC_MONITORING_ENABLED", "true")

    with ephemeral_integration_environment() as env:
        monkeypatch.setenv("SYNTHETIC_MONITORING_TRITON_ENDPOINT", env.triton_endpoint)
        monkeypatch.setenv("SYNTHETIC_MONITORING_TRITON_MODEL", "ui-detector")

        client = TestClient(create_app())
        forbidden = client.get("/api/v1/monitoring/synthetic", headers={"X-API-Key": "viewer-key"})
        allowed = client.get("/api/v1/monitoring/synthetic", headers={"X-API-Key": "admin-key"})

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
