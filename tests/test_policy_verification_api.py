from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.policy_verification import (
    JsonFilePolicyVerificationStore,
    PolicyVerificationService,
)


def test_policy_verification_detects_conflicts_and_reports_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    deny_rule = client.post(
        "/api/v1/policy/verification/rules/deny-click",
        headers={"X-API-Key": "admin-key"},
        json={
            "effect": "deny",
            "priority": 50,
            "action_patterns": ["click:*"],
            "jurisdictions": ["global"],
            "requires_authorization": True,
            "requires_region_allowed": None,
            "min_risk_score": 0.2,
            "max_risk_score": 0.9,
            "enabled": True,
            "metadata": {"owner": "security"},
        },
    )
    assert deny_rule.status_code == 200

    allow_rule = client.post(
        "/api/v1/policy/verification/rules/allow-click",
        headers={"X-API-Key": "admin-key"},
        json={
            "effect": "allow",
            "priority": 50,
            "action_patterns": ["click:*"],
            "jurisdictions": ["global"],
            "requires_authorization": True,
            "requires_region_allowed": None,
            "min_risk_score": 0.1,
            "max_risk_score": 0.8,
            "enabled": True,
            "metadata": {"owner": "product"},
        },
    )
    assert allow_rule.status_code == 200

    listed_rules = client.get(
        "/api/v1/policy/verification/rules",
        headers={"X-API-Key": "admin-key"},
    )
    assert listed_rules.status_code == 200
    assert listed_rules.json()["total"] == 2

    report = client.post(
        "/api/v1/policy/verification/validate",
        headers={"X-API-Key": "operator-key"},
        json={"include_disabled": False},
    )
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["tenant_id"] == "tenant-a"
    assert report_payload["conflict_count"] >= 1
    assert report_payload["severity"] in {"medium", "high"}
    assert any(item["conflict_type"] in {"priority_conflict", "precedence_conflict"} for item in report_payload["conflicts"])

    report_id = report_payload["report_id"]

    listed_reports = client.get(
        "/api/v1/policy/verification/reports",
        headers={"X-API-Key": "operator-key"},
    )
    assert listed_reports.status_code == 200
    assert listed_reports.json()["total"] >= 1

    fetched_report = client.get(
        f"/api/v1/policy/verification/reports/{report_id}",
        headers={"X-API-Key": "operator-key"},
    )
    assert fetched_report.status_code == 200
    assert fetched_report.json()["report_id"] == report_id



def test_policy_verification_no_conflict_path(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    worker_rule = client.post(
        "/api/v1/policy/verification/rules/allow-worker",
        headers={"X-API-Key": "admin-key"},
        json={
            "effect": "allow",
            "priority": 20,
            "action_patterns": ["worker:*"],
            "jurisdictions": ["us"],
            "requires_authorization": None,
            "requires_region_allowed": True,
            "min_risk_score": 0.0,
            "max_risk_score": 0.3,
            "enabled": True,
            "metadata": {},
        },
    )
    assert worker_rule.status_code == 200

    click_rule = client.post(
        "/api/v1/policy/verification/rules/deny-click",
        headers={"X-API-Key": "admin-key"},
        json={
            "effect": "deny",
            "priority": 90,
            "action_patterns": ["click:*"],
            "jurisdictions": ["eu"],
            "requires_authorization": None,
            "requires_region_allowed": None,
            "min_risk_score": 0.6,
            "max_risk_score": 1.0,
            "enabled": True,
            "metadata": {},
        },
    )
    assert click_rule.status_code == 200

    report = client.post(
        "/api/v1/policy/verification/validate",
        headers={"X-API-Key": "operator-key"},
        json={"include_disabled": False},
    )
    assert report.status_code == 200
    payload = report.json()
    assert payload["conflict_count"] == 0
    assert payload["severity"] == "none"



def test_policy_verification_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a,admin-key:tenant-a")

    client = TestClient(create_app())

    forbidden_upsert = client.post(
        "/api/v1/policy/verification/rules/r1",
        headers={"X-API-Key": "operator-key"},
        json={
            "effect": "allow",
            "priority": 10,
            "action_patterns": ["*"],
            "jurisdictions": ["global"],
            "enabled": True,
            "metadata": {},
        },
    )
    assert forbidden_upsert.status_code == 403

    seed = client.post(
        "/api/v1/policy/verification/rules/r1",
        headers={"X-API-Key": "admin-key"},
        json={
            "effect": "allow",
            "priority": 10,
            "action_patterns": ["*"],
            "jurisdictions": ["global"],
            "enabled": True,
            "metadata": {},
        },
    )
    assert seed.status_code == 200

    forbidden_validate = client.post(
        "/api/v1/policy/verification/validate",
        headers={"X-API-Key": "viewer-key"},
        json={"include_disabled": False},
    )
    assert forbidden_validate.status_code == 403

    legacy_validate = client.post(
        "/policy/verification/validate",
        headers={"X-API-Key": "operator-key"},
        json={"include_disabled": True},
    )
    assert legacy_validate.status_code == 200
    assert legacy_validate.headers.get("Deprecation") == "true"

    report_id = legacy_validate.json()["report_id"]

    legacy_report = client.get(
        f"/policy/verification/reports/{report_id}",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_report.status_code == 200
    assert legacy_report.headers.get("Deprecation") == "true"



def test_json_file_policy_verification_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "policy-verification.json"
    service = PolicyVerificationService(store=JsonFilePolicyVerificationStore(str(store_path)))

    service.upsert_rule(
        rule_id="deny-click",
        tenant_id="tenant-a",
        effect="deny",
        priority=50,
        action_patterns=["click:*"],
        jurisdictions=["global"],
        requires_authorization=True,
        requires_region_allowed=None,
        min_risk_score=0.1,
        max_risk_score=0.9,
        enabled=True,
        metadata={"source": "unit-test"},
    )
    service.upsert_rule(
        rule_id="allow-click",
        tenant_id="tenant-a",
        effect="allow",
        priority=50,
        action_patterns=["click:*"],
        jurisdictions=["global"],
        requires_authorization=True,
        requires_region_allowed=None,
        min_risk_score=0.2,
        max_risk_score=0.8,
        enabled=True,
        metadata={"source": "unit-test"},
    )

    report = service.verify(tenant_id="tenant-a", include_disabled=False)
    assert report["conflict_count"] >= 1

    reloaded = PolicyVerificationService(store=JsonFilePolicyVerificationStore(str(store_path)))
    rules = reloaded.list_rules(tenant_id="tenant-a")
    reports = reloaded.list_reports(tenant_id="tenant-a")

    assert len(rules) == 2
    assert len(reports) >= 1
