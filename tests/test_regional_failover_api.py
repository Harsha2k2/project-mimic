from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.multi_region_control_plane import InMemoryMultiRegionControlPlaneStore, MultiRegionControlPlaneService
from project_mimic.regional_failover import JsonFileRegionalFailoverStore, RegionalFailoverOrchestrator


def _seed_regions(client: TestClient) -> None:
    us = client.post(
        "/api/v1/control-plane/regions/us-east",
        headers={"X-API-Key": "admin-key"},
        json={
            "endpoint": "https://cp-us.example.internal",
            "traffic_weight": 1.0,
            "write_enabled": True,
            "read_enabled": True,
            "priority": 10,
        },
    )
    assert us.status_code == 200

    eu = client.post(
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
    assert eu.status_code == 200


def test_regional_failover_policy_apply_execute_recover_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())
    _seed_regions(client)

    created = client.post(
        "/api/v1/control-plane/failover/policies/global-primary",
        headers={"X-API-Key": "admin-key"},
        json={
            "primary_region": "us-east",
            "secondary_region": "eu-west",
            "read_traffic_percent": {"us-east": 80, "eu-west": 20},
            "write_region": "us-east",
            "auto_failback": True,
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["policy_id"] == "global-primary"
    assert created_payload["read_traffic_percent"]["us-east"] == 80.0

    applied = client.post(
        "/api/v1/control-plane/failover/policies/global-primary/apply",
        headers={"X-API-Key": "admin-key"},
    )
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert applied_payload["policy_id"] == "global-primary"
    assert applied_payload["write_region"] == "us-east"

    failover = client.post(
        "/api/v1/control-plane/failover/execute",
        headers={"X-API-Key": "admin-key"},
        json={
            "policy_id": "global-primary",
            "target_region": "eu-west",
            "reason": "simulated regional outage",
        },
    )
    assert failover.status_code == 200
    failover_payload = failover.json()
    assert failover_payload["active"] is True
    assert failover_payload["target_region"] == "eu-west"

    status = client.get(
        "/api/v1/control-plane/failover/status/global-primary",
        headers={"X-API-Key": "operator-key"},
    )
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["active"] is True
    assert status_payload["target_region"] == "eu-west"

    recovered = client.post(
        "/api/v1/control-plane/failover/recover",
        headers={"X-API-Key": "admin-key"},
        json={"policy_id": "global-primary", "reason": "region recovered"},
    )
    assert recovered.status_code == 200
    recovered_payload = recovered.json()
    assert recovered_payload["active"] is False
    assert recovered_payload["recovered_by"] is not None


def test_regional_failover_roles_and_legacy_routes(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())
    _seed_regions(client)

    forbidden_policy_upsert = client.post(
        "/api/v1/control-plane/failover/policies/global-primary",
        headers={"X-API-Key": "operator-key"},
        json={
            "primary_region": "us-east",
            "secondary_region": "eu-west",
            "read_traffic_percent": {"us-east": 80, "eu-west": 20},
        },
    )
    assert forbidden_policy_upsert.status_code == 403

    create_policy = client.post(
        "/api/v1/control-plane/failover/policies/global-primary",
        headers={"X-API-Key": "admin-key"},
        json={
            "primary_region": "us-east",
            "secondary_region": "eu-west",
            "read_traffic_percent": {"us-east": 80, "eu-west": 20},
        },
    )
    assert create_policy.status_code == 200

    forbidden_status = client.get(
        "/api/v1/control-plane/failover/status/global-primary",
        headers={"X-API-Key": "viewer-key"},
    )
    assert forbidden_status.status_code == 403

    legacy_policy = client.post(
        "/control-plane/failover/policies/global-primary",
        headers={"X-API-Key": "admin-key"},
        json={
            "primary_region": "us-east",
            "secondary_region": "eu-west",
            "read_traffic_percent": {"us-east": 70, "eu-west": 30},
        },
    )
    assert legacy_policy.status_code == 200
    assert legacy_policy.headers.get("Deprecation") == "true"

    legacy_list = client.get(
        "/control-plane/failover/policies",
        headers={"X-API-Key": "admin-key"},
    )
    assert legacy_list.status_code == 200
    assert legacy_list.headers.get("Deprecation") == "true"

    legacy_status = client.get(
        "/control-plane/failover/status/global-primary",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_status.status_code == 200
    assert legacy_status.headers.get("Deprecation") == "true"


def test_regional_failover_store_round_trip(tmp_path: Path) -> None:
    cp_service = MultiRegionControlPlaneService(store=InMemoryMultiRegionControlPlaneStore())
    cp_service.upsert_region(region_id="us-east", endpoint="https://cp-us.example.internal")
    cp_service.upsert_region(region_id="eu-west", endpoint="https://cp-eu.example.internal")

    store_path = tmp_path / "regional-failover.json"
    orchestrator = RegionalFailoverOrchestrator(
        control_plane=cp_service,
        store=JsonFileRegionalFailoverStore(str(store_path)),
    )

    orchestrator.upsert_policy(
        policy_id="global-primary",
        primary_region="us-east",
        secondary_region="eu-west",
        read_traffic_percent={"us-east": 90, "eu-west": 10},
        write_region="us-east",
        auto_failback=True,
    )
    orchestrator.apply_policy(policy_id="global-primary", initiated_by="test")
    orchestrator.execute_failover(
        policy_id="global-primary",
        target_region="eu-west",
        reason="test outage",
        initiated_by="test",
    )

    reloaded = RegionalFailoverOrchestrator(
        control_plane=cp_service,
        store=JsonFileRegionalFailoverStore(str(store_path)),
    )
    status = reloaded.status(policy_id="global-primary")
    policy = reloaded.get_policy(policy_id="global-primary")

    assert status["active"] is True
    assert status["target_region"] == "eu-west"
    assert policy["primary_region"] == "us-east"
