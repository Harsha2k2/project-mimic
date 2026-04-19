from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.billing import BillingPrimitives, JsonFileBillingStore


def test_billing_plan_subscription_overage_and_report_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    plan = client.post(
        "/api/v1/billing/plans",
        headers={"X-API-Key": "admin-key"},
        json={
            "plan_id": "starter",
            "description": "Starter plan",
            "included_units": {"api_request": 2.0},
            "hard_limits": True,
            "overage_buffer_units": {"api_request": 0.0},
        },
    )
    assert plan.status_code == 200

    subscription = client.post(
        "/api/v1/billing/subscriptions/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={"plan_id": "starter", "overage_protection": True},
    )
    assert subscription.status_code == 200

    for _ in range(4):
        response = client.get("/api/v1/metrics", headers={"X-API-Key": "operator-key"})
        assert response.status_code == 200

    month = datetime.now(timezone.utc).strftime("%Y-%m")

    overage = client.get(
        "/api/v1/billing/overage/tenant-op",
        headers={"X-API-Key": "admin-key"},
        params={"month": month},
    )
    assert overage.status_code == 200
    overage_payload = overage.json()
    assert overage_payload["plan_id"] == "starter"
    assert overage_payload["exceeded_dimensions"]["api_request"] >= 1.0
    assert "api_request" in overage_payload["blocked_dimensions"]

    report = client.get(
        "/api/v1/billing/reports/tenant-op",
        headers={"X-API-Key": "admin-key"},
        params={"month": month},
    )
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["month"] == month
    assert report_payload["plan_id"] == "starter"


def test_billing_overage_protection_blocks_requests_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")
    monkeypatch.setenv("BILLING_ENFORCEMENT_ENABLED", "true")

    client = TestClient(create_app())

    create_plan = client.post(
        "/api/v1/billing/plans",
        headers={"X-API-Key": "admin-key"},
        json={
            "plan_id": "strict",
            "included_units": {"api_request": 1.0},
            "hard_limits": True,
            "overage_buffer_units": {"api_request": 0.0},
        },
    )
    assert create_plan.status_code == 200

    assign_plan = client.post(
        "/api/v1/billing/subscriptions/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={"plan_id": "strict", "overage_protection": True},
    )
    assert assign_plan.status_code == 200

    first = client.get("/api/v1/metrics", headers={"X-API-Key": "operator-key"})
    second = client.get("/api/v1/metrics", headers={"X-API-Key": "operator-key"})
    third = client.get("/api/v1/metrics", headers={"X-API-Key": "operator-key"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 402
    assert third.json()["error"]["code"] == "QUOTA_EXCEEDED"


def test_billing_routes_require_admin_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")

    client = TestClient(create_app())

    forbidden = client.get("/api/v1/billing/plans", headers={"X-API-Key": "viewer-key"})
    assert forbidden.status_code == 403

    legacy_plan = client.post(
        "/billing/plans",
        headers={"X-API-Key": "admin-key"},
        json={"plan_id": "legacy-plan", "included_units": {"api_request": 10.0}, "hard_limits": True},
    )
    assert legacy_plan.status_code == 200
    assert legacy_plan.headers.get("Deprecation") == "true"

    legacy_list = client.get("/billing/plans", headers={"X-API-Key": "admin-key"})
    assert legacy_list.status_code == 200
    assert legacy_list.headers.get("Deprecation") == "true"

    legacy_get = client.get("/billing/plans/legacy-plan", headers={"X-API-Key": "admin-key"})
    assert legacy_get.status_code == 200
    assert legacy_get.headers.get("Deprecation") == "true"


def test_json_file_billing_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "billing.json"
    store = JsonFileBillingStore(str(store_path))
    billing = BillingPrimitives(store=store)

    billing.upsert_plan(
        plan_id="pro",
        description="Pro tier",
        included_units={"api_request": 100.0},
        hard_limits=True,
        overage_buffer_units={"api_request": 10.0},
    )
    billing.assign_plan(tenant_id="tenant-a", plan_id="pro", overage_protection=True)

    reloaded = BillingPrimitives(store=store)
    plan = reloaded.get_plan(plan_id="pro")
    subscription = reloaded.get_subscription(tenant_id="tenant-a")

    assert plan["plan_id"] == "pro"
    assert subscription["plan_id"] == "pro"
