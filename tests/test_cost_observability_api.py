from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.cost_observability import CostObservabilityService, JsonFileCostObservabilityStore


def test_cost_observability_dashboard_gpu_queue_storage_egress(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-a")

    client = TestClient(create_app())

    first = client.post(
        "/api/v1/cost/observability/snapshots/day-1",
        headers={"X-API-Key": "operator-key"},
        json={
            "period_start_day": 20001,
            "period_end_day": 20001,
            "gpu_hours": 14.0,
            "queue_compute_hours": 8.0,
            "storage_gb_month": 120.0,
            "egress_gb": 50.0,
            "rates": {
                "gpu_hours": 2.5,
                "queue_compute_hours": 0.5,
                "storage_gb_month": 0.1,
                "egress_gb": 0.12,
            },
            "metadata": {"source": "collector-a"},
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/cost/observability/snapshots/day-2",
        headers={"X-API-Key": "operator-key"},
        json={
            "period_start_day": 20002,
            "period_end_day": 20002,
            "gpu_hours": 16.0,
            "queue_compute_hours": 7.5,
            "storage_gb_month": 122.0,
            "egress_gb": 58.0,
            "rates": {
                "gpu_hours": 2.5,
                "queue_compute_hours": 0.5,
                "storage_gb_month": 0.1,
                "egress_gb": 0.12,
            },
            "metadata": {"source": "collector-a"},
        },
    )
    assert second.status_code == 200

    snapshots = client.get(
        "/api/v1/cost/observability/snapshots",
        headers={"X-API-Key": "operator-key"},
    )
    assert snapshots.status_code == 200
    assert snapshots.json()["total"] >= 2

    dashboard = client.get(
        "/api/v1/cost/observability/dashboard",
        headers={"X-API-Key": "operator-key"},
        params={"lookback": 12},
    )
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["snapshot_count"] >= 2
    assert payload["totals"]["gpu_cost"] > 0
    assert payload["totals"]["queue_cost"] > 0
    assert payload["totals"]["storage_cost"] > 0
    assert payload["totals"]["egress_cost"] > 0
    assert payload["latest_snapshot"] is not None


def test_cost_observability_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/cost/observability/snapshots/day-1",
        headers={"X-API-Key": "viewer-key"},
        json={
            "period_start_day": 20001,
            "period_end_day": 20001,
            "gpu_hours": 14.0,
            "queue_compute_hours": 8.0,
            "storage_gb_month": 120.0,
            "egress_gb": 50.0,
            "rates": {},
            "metadata": {},
        },
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/v1/cost/observability/snapshots/day-1",
        headers={"X-API-Key": "operator-key"},
        json={
            "period_start_day": 20001,
            "period_end_day": 20001,
            "gpu_hours": 14.0,
            "queue_compute_hours": 8.0,
            "storage_gb_month": 120.0,
            "egress_gb": 50.0,
            "rates": {},
            "metadata": {},
        },
    )
    assert created.status_code == 200

    legacy_dashboard = client.get(
        "/cost/observability/dashboard",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_dashboard.status_code == 200
    assert legacy_dashboard.headers.get("Deprecation") == "true"



def test_json_file_cost_observability_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "cost-observability.json"
    service = CostObservabilityService(store=JsonFileCostObservabilityStore(str(store_path)))

    service.record_snapshot(
        tenant_id="tenant-a",
        snapshot_id="day-1",
        period_start_day=20001,
        period_end_day=20001,
        gpu_hours=14.0,
        queue_compute_hours=8.0,
        storage_gb_month=120.0,
        egress_gb=50.0,
        rates={"gpu_hours": 2.5, "queue_compute_hours": 0.5, "storage_gb_month": 0.1, "egress_gb": 0.12},
        metadata={"source": "collector-a"},
    )

    reloaded = CostObservabilityService(store=JsonFileCostObservabilityStore(str(store_path)))
    listed = reloaded.list_snapshots(tenant_id="tenant-a")
    dashboard = reloaded.get_dashboard(tenant_id="tenant-a", lookback=12)

    assert len(listed) == 1
    assert dashboard["snapshot_count"] == 1
    assert dashboard["totals"]["total_cost"] > 0
