from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.governance_controls import ConsentTargetGovernanceService, JsonFileGovernancePolicyStore


def test_governance_policy_management_and_evaluation_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/governance/policies/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={
            "consent_required": True,
            "allowed_target_patterns": ["button:*", "input:*"],
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["tenant_id"] == "tenant-op"
    assert created_payload["consent_required"] is True
    assert created_payload["allowed_target_patterns"] == ["button:*", "input:*"]

    listed = client.get("/api/v1/governance/policies", headers={"X-API-Key": "admin-key"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    fetched = client.get("/api/v1/governance/policies/tenant-op", headers={"X-API-Key": "admin-key"})
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == "tenant-op"

    denied_no_consent = client.post(
        "/api/v1/governance/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "click", "target": "button:submit", "consent_granted": False},
    )
    assert denied_no_consent.status_code == 200
    assert denied_no_consent.json()["allowed"] is False
    assert denied_no_consent.json()["reason"] == "consent_required"

    denied_target = client.post(
        "/api/v1/governance/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "click", "target": "link:next", "consent_granted": True},
    )
    assert denied_target.status_code == 200
    assert denied_target.json()["allowed"] is False
    assert denied_target.json()["reason"] == "target_not_allowlisted"

    allowed = client.post(
        "/api/v1/governance/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "click", "target": "button:submit", "consent_granted": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True
    assert allowed.json()["reason"] == "target_allowlisted"


def test_governance_enforcement_blocks_step_without_consent_or_allowed_target(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")
    monkeypatch.setenv("GOVERNANCE_ENFORCEMENT_ENABLED", "true")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/governance/policies/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={"consent_required": True, "allowed_target_patterns": ["button:*"]},
    )
    assert created.status_code == 200

    session = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "operator-key"},
        json={"goal": "governance-step", "max_steps": 3},
    )
    assert session.status_code == 200
    session_id = session.json()["session_id"]

    blocked_no_consent = client.post(
        f"/api/v1/sessions/{session_id}/step",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "click", "target": "button:submit"},
    )
    assert blocked_no_consent.status_code == 403
    assert blocked_no_consent.json()["error"]["code"] == "FORBIDDEN"

    blocked_target = client.post(
        f"/api/v1/sessions/{session_id}/step",
        headers={"X-API-Key": "operator-key", "X-Consent-Granted": "true"},
        json={"action_type": "click", "target": "link:next"},
    )
    assert blocked_target.status_code == 403
    assert blocked_target.json()["error"]["code"] == "FORBIDDEN"

    allowed = client.post(
        f"/api/v1/sessions/{session_id}/step",
        headers={"X-API-Key": "operator-key"},
        json={
            "action_type": "click",
            "target": "button:submit",
            "metadata": {"consent_granted": True},
        },
    )
    assert allowed.status_code == 200


def test_governance_routes_require_roles_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-op")

    client = TestClient(create_app())

    forbidden_list = client.get("/api/v1/governance/policies", headers={"X-API-Key": "viewer-key"})
    assert forbidden_list.status_code == 403

    forbidden_upsert = client.post(
        "/api/v1/governance/policies/tenant-op",
        headers={"X-API-Key": "operator-key"},
        json={"consent_required": True, "allowed_target_patterns": ["button:*"]},
    )
    assert forbidden_upsert.status_code == 403

    operator_evaluate = client.post(
        "/api/v1/governance/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "wait", "consent_granted": False},
    )
    assert operator_evaluate.status_code == 200
    assert operator_evaluate.json()["reason"] == "no_governance_policy"

    legacy_upsert = client.post(
        "/governance/policies/tenant-op",
        headers={"X-API-Key": "admin-key"},
        json={"consent_required": True, "allowed_target_patterns": ["button:*"]},
    )
    assert legacy_upsert.status_code == 200
    assert legacy_upsert.headers.get("Deprecation") == "true"

    legacy_list = client.get("/governance/policies", headers={"X-API-Key": "admin-key"})
    assert legacy_list.status_code == 200
    assert legacy_list.headers.get("Deprecation") == "true"

    legacy_get = client.get("/governance/policies/tenant-op", headers={"X-API-Key": "admin-key"})
    assert legacy_get.status_code == 200
    assert legacy_get.headers.get("Deprecation") == "true"

    legacy_evaluate = client.post(
        "/governance/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "click", "target": "button:ok", "consent_granted": True},
    )
    assert legacy_evaluate.status_code == 200
    assert legacy_evaluate.headers.get("Deprecation") == "true"


def test_json_file_governance_policy_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "governance-policy.json"
    store = JsonFileGovernancePolicyStore(str(store_path))
    service = ConsentTargetGovernanceService(store=store)

    service.upsert_policy(
        tenant_id="tenant-a",
        consent_required=True,
        allowed_target_patterns=["button:*", "input:*"],
    )

    reloaded = ConsentTargetGovernanceService(store=store)
    fetched = reloaded.get_policy(tenant_id="tenant-a")
    denied = reloaded.evaluate(
        tenant_id="tenant-a",
        action_type="click",
        target="link:next",
        consent_granted=True,
    )
    allowed = reloaded.evaluate(
        tenant_id="tenant-a",
        action_type="click",
        target="button:submit",
        consent_granted=True,
    )

    assert fetched["tenant_id"] == "tenant-a"
    assert fetched["consent_required"] is True
    assert fetched["allowed_target_patterns"] == ["button:*", "input:*"]
    assert denied["allowed"] is False
    assert denied["reason"] == "target_not_allowlisted"
    assert allowed["allowed"] is True
    assert allowed["reason"] == "target_allowlisted"
