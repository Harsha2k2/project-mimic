from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.policy_explorer import JsonFilePolicyDecisionStore, PolicyDecisionExplorer


def test_policy_decision_evaluate_list_and_detail_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "operator-key:operator")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/policy/decisions/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={
            "actor_id": "agent-1",
            "site_id": "site-a",
            "region_allowed": True,
            "has_authorization": True,
            "risk_score": 0.95,
            "action": "click",
            "simulate": False,
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["allowed"] is False
    assert created_payload["applied_rule_id"] == "risk_threshold"
    assert any(
        item["rule_id"] == "risk_threshold" and item["verdict"] == "deny"
        for item in created_payload["explanations"]
    )

    decision_id = created_payload["decision_id"]

    listed = client.get(
        "/api/v1/policy/decisions",
        headers={"X-API-Key": "operator-key"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    denied_only = client.get(
        "/api/v1/policy/decisions",
        headers={"X-API-Key": "operator-key"},
        params={"allowed": "false"},
    )
    assert denied_only.status_code == 200
    assert denied_only.json()["total"] == 1

    detail = client.get(
        f"/api/v1/policy/decisions/{decision_id}",
        headers={"X-API-Key": "operator-key"},
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["decision_id"] == decision_id
    assert detail_payload["reason"] == "risk threshold exceeded"


def test_policy_decision_routes_enforce_tenant_isolation(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "tenant-a-key,tenant-b-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "tenant-a-key:operator,tenant-b-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "tenant-a-key:tenant-a,tenant-b-key:tenant-b")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/policy/decisions/evaluate",
        headers={"X-API-Key": "tenant-a-key"},
        json={
            "actor_id": "agent-a",
            "site_id": "site-1",
            "region_allowed": True,
            "has_authorization": True,
            "risk_score": 0.1,
            "action": "click",
        },
    )
    assert created.status_code == 200
    decision_id = created.json()["decision_id"]

    list_other_tenant = client.get(
        "/api/v1/policy/decisions",
        headers={"X-API-Key": "tenant-b-key"},
    )
    assert list_other_tenant.status_code == 200
    assert list_other_tenant.json()["total"] == 0

    detail_other_tenant = client.get(
        f"/api/v1/policy/decisions/{decision_id}",
        headers={"X-API-Key": "tenant-b-key"},
    )
    assert detail_other_tenant.status_code == 404


def test_operator_policy_explorer_requires_admin_and_renders_trails(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/policy/decisions/evaluate",
        headers={"X-API-Key": "admin-key"},
        json={
            "actor_id": "agent-admin",
            "site_id": "site-admin",
            "region_allowed": True,
            "has_authorization": False,
            "risk_score": 0.1,
            "action": "click",
        },
    )
    assert created.status_code == 200
    decision_id = created.json()["decision_id"]

    denied = client.get("/api/v1/operator/policy", headers={"X-API-Key": "viewer-key"})
    assert denied.status_code == 403

    allowed = client.get(
        "/api/v1/operator/policy",
        headers={"X-API-Key": "admin-key"},
        params={"decision_id": decision_id},
    )
    assert allowed.status_code == 200
    assert "Policy Decision Explorer" in allowed.text
    assert "Explanation Trail" in allowed.text
    assert decision_id in allowed.text

    snapshot = client.get(
        "/api/v1/operator/policy/snapshot",
        headers={"X-API-Key": "admin-key"},
        params={"decision_id": decision_id},
    )
    assert snapshot.status_code == 200
    snapshot_payload = snapshot.json()
    assert snapshot_payload["selected"]["decision_id"] == decision_id


def test_policy_explorer_legacy_routes_emit_deprecation_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "operator-key:operator,admin-key:admin")

    client = TestClient(create_app())

    created = client.post(
        "/policy/decisions/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={
            "actor_id": "agent-legacy",
            "site_id": "site-legacy",
            "region_allowed": True,
            "has_authorization": True,
            "risk_score": 0.2,
            "action": "click",
        },
    )
    assert created.status_code == 200
    assert created.headers.get("Deprecation") == "true"
    decision_id = created.json()["decision_id"]

    listed = client.get("/policy/decisions", headers={"X-API-Key": "operator-key"})
    assert listed.status_code == 200
    assert listed.headers.get("Deprecation") == "true"

    detail = client.get(f"/policy/decisions/{decision_id}", headers={"X-API-Key": "operator-key"})
    assert detail.status_code == 200
    assert detail.headers.get("Deprecation") == "true"

    ui = client.get("/operator/policy", headers={"X-API-Key": "admin-key"})
    assert ui.status_code == 200
    assert ui.headers.get("Deprecation") == "true"

    snapshot = client.get("/operator/policy/snapshot", headers={"X-API-Key": "admin-key"})
    assert snapshot.status_code == 200
    assert snapshot.headers.get("Deprecation") == "true"


def test_json_file_policy_decision_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "policy-decisions.json"
    store = JsonFilePolicyDecisionStore(str(store_path))
    explorer = PolicyDecisionExplorer(store=store, risk_threshold=0.6)

    created = explorer.evaluate(
        tenant_id="tenant-a",
        actor_id="agent-1",
        site_id="site-a",
        region_allowed=True,
        has_authorization=True,
        risk_score=0.1,
        action="click",
    )

    reloaded = PolicyDecisionExplorer(store=store, risk_threshold=0.6)
    listed = reloaded.list(tenant_id="tenant-a")

    assert len(listed) == 1
    assert listed[0]["decision_id"] == created["decision_id"]
    assert listed[0]["explanations"]
