from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.autonomous_remediation import (
    AutonomousRemediationService,
    JsonFileAutonomousRemediationStore,
)


def test_autonomous_remediation_trigger_executes_supported_actions(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    feature_flag_seed = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={
            "flag_key": "remediate-automation",
            "description": "Remediation gate",
            "enabled": True,
            "rollout_percentage": 100,
            "tenant_allowlist": [],
            "subject_allowlist": [],
            "metadata": {},
        },
    )
    assert feature_flag_seed.status_code == 200

    signature = client.post(
        "/api/v1/remediation/autonomous/signatures/queue-recovery",
        headers={"X-API-Key": "admin-key"},
        json={
            "incident_class": "checkpoint_missing",
            "failure_code": "checkpoint_recovery",
            "threshold": 3.0,
            "cooldown_seconds": 0,
            "enabled": True,
            "action_plan": [
                {"action_type": "queue.requeue_expired_leases", "parameters": {}},
                {
                    "action_type": "feature_flag.disable",
                    "parameters": {"flag_key": "remediate-automation"},
                },
            ],
        },
    )
    assert signature.status_code == 200

    execute = client.post(
        "/api/v1/remediation/autonomous/execute",
        headers={"X-API-Key": "operator-key"},
        json={
            "signature_id": "queue-recovery",
            "observed_value": 4.0,
            "signal_label": "dead_letter_count",
            "execute": True,
            "context": {"source": "synthetic-monitor"},
        },
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["matched"] is True
    assert payload["executed"] is True
    assert payload["reason"] == "actions_executed"
    assert len(payload["action_results"]) == 2
    assert all(item["success"] is True for item in payload["action_results"])

    list_exec = client.get(
        "/api/v1/remediation/autonomous/executions",
        headers={"X-API-Key": "operator-key"},
    )
    assert list_exec.status_code == 200
    assert list_exec.json()["total"] >= 1



def test_autonomous_remediation_trigger_below_threshold_and_dry_run(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    signature = client.post(
        "/api/v1/remediation/autonomous/signatures/latency-remediate",
        headers={"X-API-Key": "admin-key"},
        json={
            "incident_class": "triton_inference_error",
            "failure_code": "timeout",
            "threshold": 100.0,
            "cooldown_seconds": 0,
            "enabled": True,
            "action_plan": [
                {
                    "action_type": "control_plane.failover_execute",
                    "parameters": {
                        "policy_id": "missing-policy",
                        "target_region": "us-east",
                    },
                }
            ],
        },
    )
    assert signature.status_code == 200

    below_threshold = client.post(
        "/api/v1/remediation/autonomous/execute",
        headers={"X-API-Key": "operator-key"},
        json={
            "signature_id": "latency-remediate",
            "observed_value": 90.0,
            "signal_label": "inference_latency",
            "execute": True,
        },
    )
    assert below_threshold.status_code == 200
    below_payload = below_threshold.json()
    assert below_payload["matched"] is False
    assert below_payload["executed"] is False
    assert below_payload["reason"] == "below_threshold"

    dry_run = client.post(
        "/api/v1/remediation/autonomous/execute",
        headers={"X-API-Key": "operator-key"},
        json={
            "signature_id": "latency-remediate",
            "observed_value": 120.0,
            "signal_label": "inference_latency",
            "execute": False,
        },
    )
    assert dry_run.status_code == 200
    dry_payload = dry_run.json()
    assert dry_payload["matched"] is True
    assert dry_payload["executed"] is False
    assert dry_payload["reason"] == "dry_run"



def test_autonomous_remediation_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a,admin-key:tenant-a")

    client = TestClient(create_app())

    forbidden_signature_upsert = client.post(
        "/api/v1/remediation/autonomous/signatures/blocked",
        headers={"X-API-Key": "operator-key"},
        json={
            "incident_class": "api_session_conflict",
            "failure_code": None,
            "threshold": 1.0,
            "cooldown_seconds": 0,
            "enabled": True,
            "action_plan": [{"action_type": "queue.requeue_expired_leases", "parameters": {}}],
        },
    )
    assert forbidden_signature_upsert.status_code == 403

    seeded = client.post(
        "/api/v1/remediation/autonomous/signatures/blocked",
        headers={"X-API-Key": "admin-key"},
        json={
            "incident_class": "api_session_conflict",
            "failure_code": None,
            "threshold": 1.0,
            "cooldown_seconds": 0,
            "enabled": True,
            "action_plan": [{"action_type": "queue.requeue_expired_leases", "parameters": {}}],
        },
    )
    assert seeded.status_code == 200

    forbidden_execute = client.post(
        "/api/v1/remediation/autonomous/execute",
        headers={"X-API-Key": "viewer-key"},
        json={
            "signature_id": "blocked",
            "observed_value": 2.0,
            "signal_label": "session_conflicts",
            "execute": True,
        },
    )
    assert forbidden_execute.status_code == 403

    legacy_execute = client.post(
        "/remediation/autonomous/execute",
        headers={"X-API-Key": "operator-key"},
        json={
            "signature_id": "blocked",
            "observed_value": 2.0,
            "signal_label": "session_conflicts",
            "execute": True,
        },
    )
    assert legacy_execute.status_code == 200
    assert legacy_execute.headers.get("Deprecation") == "true"



def test_autonomous_remediation_json_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "autonomous-remediation.json"

    captured_actions: list[str] = []

    def _executor(action_type: str, parameters: dict[str, object], context: dict[str, object]) -> dict[str, object]:
        captured_actions.append(action_type)
        return {
            "success": True,
            "status": "succeeded",
            "details": {
                "parameters": dict(parameters),
                "signature_id": context.get("signature_id"),
            },
        }

    service = AutonomousRemediationService(
        store=JsonFileAutonomousRemediationStore(str(store_path)),
        action_executor=_executor,
    )

    service.upsert_signature(
        signature_id="queue-recovery",
        tenant_id="tenant-a",
        incident_class="checkpoint_missing",
        failure_code="checkpoint_recovery",
        threshold=2.0,
        cooldown_seconds=0,
        enabled=True,
        action_plan=[{"action_type": "queue.requeue_expired_leases", "parameters": {}}],
    )

    execution = service.trigger(
        signature_id="queue-recovery",
        tenant_id="tenant-a",
        observed_value=3.0,
        signal_label="dead_letter_count",
        execute=True,
        initiated_by="test",
        context={"source": "unit-test"},
    )

    assert execution["executed"] is True
    assert execution["reason"] == "actions_executed"
    assert captured_actions == ["queue.requeue_expired_leases"]

    reloaded = AutonomousRemediationService(
        store=JsonFileAutonomousRemediationStore(str(store_path)),
        action_executor=_executor,
    )
    signatures = reloaded.list_signatures(tenant_id="tenant-a")
    executions = reloaded.list_executions(tenant_id="tenant-a")

    assert len(signatures) == 1
    assert len(executions) == 1
    assert executions[0]["signature_id"] == "queue-recovery"
