from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.data_residency import JsonFileDataResidencyStore, TenantDataResidencyPolicyService


def test_data_residency_policy_management_and_validation_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/data-residency/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={
            "allowed_regions": ["us-east-1", "eu-west-1"],
            "default_region": "us-east-1",
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["tenant_id"] == "tenant-op"
    assert created_payload["allowed_regions"] == ["eu-west-1", "us-east-1"]
    assert created_payload["default_region"] == "us-east-1"

    listed = client.get("/api/v1/data-residency", headers={"X-API-Key": "admin-key"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    fetched = client.get("/api/v1/data-residency/tenant-op", headers={"X-API-Key": "admin-key"})
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == "tenant-op"

    allowed = client.get(
        "/api/v1/data-residency/validate",
        headers={"X-API-Key": "operator-key"},
        params={"region": "us-east-1"},
    )
    assert allowed.status_code == 200
    allowed_payload = allowed.json()
    assert allowed_payload["tenant_id"] == "tenant-op"
    assert allowed_payload["allowed"] is True
    assert allowed_payload["reason"] == "region_allowed"

    denied = client.get(
        "/api/v1/data-residency/validate",
        headers={"X-API-Key": "operator-key"},
        params={"region": "ap-south-1"},
    )
    assert denied.status_code == 200
    denied_payload = denied.json()
    assert denied_payload["tenant_id"] == "tenant-op"
    assert denied_payload["allowed"] is False
    assert denied_payload["reason"] == "region_not_permitted"


def test_data_residency_enforcement_blocks_disallowed_regions(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")
    monkeypatch.setenv("DATA_RESIDENCY_ENFORCEMENT_ENABLED", "true")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/data-residency/tenant-op",
        headers={"X-API-Key": "admin-key", "X-Region": "us-east-1"},
        json={
            "allowed_regions": ["us-east-1"],
            "default_region": "us-east-1",
        },
    )
    assert created.status_code == 200

    blocked = client.get(
        "/api/v1/metrics",
        headers={"X-API-Key": "operator-key", "X-Region": "eu-west-1"},
    )
    assert blocked.status_code == 403
    blocked_payload = blocked.json()
    assert blocked_payload["error"]["code"] == "FORBIDDEN"

    allowed = client.get(
        "/api/v1/metrics",
        headers={"X-API-Key": "operator-key", "X-Region": "us-east-1"},
    )
    assert allowed.status_code == 200


def test_data_residency_roles_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-op")

    client = TestClient(create_app())

    forbidden_list = client.get("/api/v1/data-residency", headers={"X-API-Key": "viewer-key"})
    assert forbidden_list.status_code == 403

    forbidden_upsert = client.post(
        "/api/v1/data-residency/tenant-op",
        headers={"X-API-Key": "operator-key"},
        json={"allowed_regions": ["us-east-1"]},
    )
    assert forbidden_upsert.status_code == 403

    operator_validate = client.get(
        "/api/v1/data-residency/validate",
        headers={"X-API-Key": "operator-key"},
        params={"region": "us-east-1"},
    )
    assert operator_validate.status_code == 200
    assert operator_validate.json()["reason"] == "no_residency_policy"

    legacy_upsert = client.post(
        "/data-residency/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={"allowed_regions": ["us-east-1"], "default_region": "us-east-1"},
    )
    assert legacy_upsert.status_code == 200
    assert legacy_upsert.headers.get("Deprecation") == "true"

    legacy_list = client.get("/data-residency", headers={"X-API-Key": "admin-key"})
    assert legacy_list.status_code == 200
    assert legacy_list.headers.get("Deprecation") == "true"

    legacy_validate = client.get(
        "/data-residency/validate",
        headers={"X-API-Key": "operator-key"},
        params={"region": "us-east-1"},
    )
    assert legacy_validate.status_code == 200
    assert legacy_validate.headers.get("Deprecation") == "true"

    legacy_get = client.get("/data-residency/tenant-op", headers={"X-API-Key": "admin-key"})
    assert legacy_get.status_code == 200
    assert legacy_get.headers.get("Deprecation") == "true"


def test_json_file_data_residency_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "data-residency.json"
    store = JsonFileDataResidencyStore(str(store_path))
    service = TenantDataResidencyPolicyService(store=store)

    service.set_policy(
        tenant_id="tenant-a",
        allowed_regions=["eu-west-1", "us-east-1"],
        default_region="eu-west-1",
    )

    reloaded = TenantDataResidencyPolicyService(store=store)
    fetched = reloaded.get_policy(tenant_id="tenant-a")
    validation = reloaded.validate(tenant_id="tenant-a", region=None)

    assert fetched["tenant_id"] == "tenant-a"
    assert fetched["allowed_regions"] == ["eu-west-1", "us-east-1"]
    assert validation["allowed"] is True
    assert validation["region"] == "eu-west-1"
