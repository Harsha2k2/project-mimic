from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.governance_approval import (
    GovernanceApprovalWorkflowService,
    JsonFileGovernanceApprovalStore,
)


def test_governance_approval_high_risk_submit_approve_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-a")

    client = TestClient(create_app())

    submitted = client.post(
        "/api/v1/governance/approvals/requests/change-001",
        headers={"X-API-Key": "operator-key"},
        json={
            "policy_id": "policy-risk-1",
            "change_summary": "Expand allowlist to include partner region",
            "risk_score": 0.92,
            "submitted_by": "author-1",
            "required_approvals": 2,
            "metadata": {"ticket": "SEC-101"},
        },
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending"

    first_approval = client.post(
        "/api/v1/governance/approvals/requests/change-001/approve",
        headers={"X-API-Key": "operator-key"},
        json={"approver": "approver-a", "comment": "looks good"},
    )
    assert first_approval.status_code == 200
    assert first_approval.json()["status"] == "pending"

    second_approval = client.post(
        "/api/v1/governance/approvals/requests/change-001/approve",
        headers={"X-API-Key": "operator-key"},
        json={"approver": "approver-b", "comment": "approved"},
    )
    assert second_approval.status_code == 200
    payload = second_approval.json()
    assert payload["status"] == "approved"
    assert len(payload["approvals"]) == 2

    listed = client.get(
        "/api/v1/governance/approvals/requests",
        headers={"X-API-Key": "operator-key"},
        params={"status": "approved"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    fetched = client.get(
        "/api/v1/governance/approvals/requests/change-001",
        headers={"X-API-Key": "operator-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["request_id"] == "change-001"


def test_governance_approval_reject_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/governance/approvals/requests/change-002",
        headers={"X-API-Key": "viewer-key"},
        json={
            "policy_id": "policy-risk-2",
            "change_summary": "Enable cross-region model override",
            "risk_score": 0.95,
            "submitted_by": "author-2",
            "required_approvals": 2,
            "metadata": {},
        },
    )
    assert forbidden.status_code == 403

    submitted = client.post(
        "/api/v1/governance/approvals/requests/change-002",
        headers={"X-API-Key": "operator-key"},
        json={
            "policy_id": "policy-risk-2",
            "change_summary": "Enable cross-region model override",
            "risk_score": 0.95,
            "submitted_by": "author-2",
            "required_approvals": 2,
            "metadata": {},
        },
    )
    assert submitted.status_code == 200

    legacy_reject = client.post(
        "/governance/approvals/requests/change-002/reject",
        headers={"X-API-Key": "operator-key"},
        json={"approver": "security-lead", "reason": "missing mitigation plan"},
    )
    assert legacy_reject.status_code == 200
    assert legacy_reject.headers.get("Deprecation") == "true"
    assert legacy_reject.json()["status"] == "rejected"

    legacy_get = client.get(
        "/governance/approvals/requests/change-002",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_get.status_code == 200
    assert legacy_get.headers.get("Deprecation") == "true"


def test_json_file_governance_approval_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "governance-approval.json"
    service = GovernanceApprovalWorkflowService(store=JsonFileGovernanceApprovalStore(str(store_path)))

    service.submit_request(
        tenant_id="tenant-a",
        request_id="change-001",
        policy_id="policy-risk-1",
        change_summary="Expand allowlist to include partner region",
        risk_score=0.92,
        submitted_by="author-1",
        required_approvals=2,
        metadata={"ticket": "SEC-101"},
    )
    service.approve_request(
        tenant_id="tenant-a",
        request_id="change-001",
        approver="approver-a",
        comment="looks good",
    )

    reloaded = GovernanceApprovalWorkflowService(store=JsonFileGovernanceApprovalStore(str(store_path)))
    listed = reloaded.list_requests(tenant_id="tenant-a")
    fetched = reloaded.get_request(tenant_id="tenant-a", request_id="change-001")

    assert len(listed) == 1
    assert fetched is not None
    assert fetched["status"] == "pending"
