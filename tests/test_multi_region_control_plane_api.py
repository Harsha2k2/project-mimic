from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.multi_region_control_plane import (
    JsonFileMultiRegionControlPlaneStore,
    MultiRegionControlPlaneService,
)


def test_control_plane_region_management_and_routing_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    first = client.post(
        "/api/v1/control-plane/regions/us-east",
        headers={"X-API-Key": "admin-key"},
        json={
            "endpoint": "https://cp-us.example.internal",
            "traffic_weight": 2.0,
            "write_enabled": True,
            "read_enabled": True,
            "priority": 10,
        },
    )
    assert first.status_code == 200
    assert first.json()["region_id"] == "us-east"

    second = client.post(
        "/api/v1/control-plane/regions/eu-west",
        headers={"X-API-Key": "admin-key"},
        json={
            "endpoint": "https://cp-eu.example.internal",
            "traffic_weight": 1.0,
            "write_enabled": True,
            "read_enabled": True,
            "priority": 20,
        },
    )
    assert second.status_code == 200

    listed = client.get("/api/v1/control-plane/regions", headers={"X-API-Key": "admin-key"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 2

    topology = client.get("/api/v1/control-plane/topology", headers={"X-API-Key": "operator-key"})
    assert topology.status_code == 200
    topology_payload = topology.json()
    assert topology_payload["mode"] == "active-active"
    assert topology_payload["active_active_ready"] is True
    assert topology_payload["primary_region"] == "us-east"

    preferred = client.post(
        "/api/v1/control-plane/route",
        headers={"X-API-Key": "operator-key"},
        json={"operation": "write", "preferred_region": "eu-west"},
    )
    assert preferred.status_code == 200
    preferred_payload = preferred.json()
    assert preferred_payload["selected_region"] == "eu-west"
    assert preferred_payload["reason"] == "preferred_region_selected"

    fallback = client.post(
        "/api/v1/control-plane/route",
        headers={"X-API-Key": "operator-key"},
        json={"operation": "read", "preferred_region": "ap-south"},
    )
    assert fallback.status_code == 200
    fallback_payload = fallback.json()
    assert fallback_payload["selected_region"] in {"us-east", "eu-west"}
    assert fallback_payload["reason"] == "preferred_region_unavailable_fallback"


def test_control_plane_health_update_affects_routing(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/control-plane/regions/us-east",
        headers={"X-API-Key": "admin-key"},
        json={"endpoint": "https://cp-us.example.internal"},
    )
    assert created.status_code == 200

    unhealthy = client.post(
        "/api/v1/control-plane/regions/us-east/health",
        headers={"X-API-Key": "admin-key"},
        json={"healthy": False, "reason": "simulated outage"},
    )
    assert unhealthy.status_code == 200
    assert unhealthy.json()["healthy"] is False

    blocked = client.post(
        "/api/v1/control-plane/route",
        headers={"X-API-Key": "operator-key"},
        json={"operation": "read"},
    )
    assert blocked.status_code == 400
    assert "no healthy regions available" in blocked.json()["error"]["message"]


def test_control_plane_roles_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-op,admin-key:tenant-admin")

    client = TestClient(create_app())

    forbidden_upsert = client.post(
        "/api/v1/control-plane/regions/us-east",
        headers={"X-API-Key": "operator-key"},
        json={"endpoint": "https://cp-us.example.internal"},
    )
    assert forbidden_upsert.status_code == 403

    forbidden_topology = client.get("/api/v1/control-plane/topology", headers={"X-API-Key": "viewer-key"})
    assert forbidden_topology.status_code == 403

    legacy_upsert = client.post(
        "/control-plane/regions/us-east",
        headers={"X-API-Key": "admin-key"},
        json={"endpoint": "https://cp-us.example.internal"},
    )
    assert legacy_upsert.status_code == 200
    assert legacy_upsert.headers.get("Deprecation") == "true"

    legacy_list = client.get("/control-plane/regions", headers={"X-API-Key": "admin-key"})
    assert legacy_list.status_code == 200
    assert legacy_list.headers.get("Deprecation") == "true"

    legacy_topology = client.get("/control-plane/topology", headers={"X-API-Key": "operator-key"})
    assert legacy_topology.status_code == 200
    assert legacy_topology.headers.get("Deprecation") == "true"

    legacy_route = client.post(
        "/control-plane/route",
        headers={"X-API-Key": "operator-key"},
        json={"operation": "read"},
    )
    assert legacy_route.status_code == 200
    assert legacy_route.headers.get("Deprecation") == "true"

    tenant_override = client.post(
        "/api/v1/control-plane/route",
        headers={"X-API-Key": "operator-key"},
        json={"operation": "read", "tenant_id": "other-tenant"},
    )
    assert tenant_override.status_code == 403


def test_json_file_multi_region_control_plane_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "control-plane.json"
    store = JsonFileMultiRegionControlPlaneStore(str(store_path))
    service = MultiRegionControlPlaneService(store=store)

    service.upsert_region(
        region_id="us-east",
        endpoint="https://cp-us.example.internal",
        traffic_weight=1.5,
        write_enabled=True,
        read_enabled=True,
        priority=5,
    )
    service.update_health(region_id="us-east", healthy=False, reason="maintenance")

    reloaded = MultiRegionControlPlaneService(store=store)
    region = reloaded.get_region(region_id="us-east")
    topology = reloaded.topology_snapshot()

    assert region["region_id"] == "us-east"
    assert region["healthy"] is False
    assert region["health_reason"] == "maintenance"
    assert topology["mode"] == "active-active"
    assert topology["total_regions"] == 1
