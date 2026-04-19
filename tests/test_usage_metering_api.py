from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.usage_metering import JsonFileUsageMeteringStore, TenantUsageMetering


def test_usage_metering_tracks_billable_dimensions(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    create_flag = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={"flag_key": "metered-flag", "enabled": True, "rollout_percentage": 100},
    )
    assert create_flag.status_code == 200

    created_session = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "operator-key"},
        json={"goal": "metering-goal", "max_steps": 2},
    )
    assert created_session.status_code == 200
    session_id = created_session.json()["session_id"]

    stepped = client.post(
        f"/api/v1/sessions/{session_id}/step",
        headers={"X-API-Key": "operator-key"},
        json={"action_type": "click", "target": "button", "x": 1, "y": 1},
    )
    assert stepped.status_code == 200

    submitted_job = client.post(
        "/api/v1/jobs",
        headers={"X-API-Key": "operator-key"},
        json={"job_type": "capture", "input": {"session_id": session_id}},
    )
    assert submitted_job.status_code == 200

    submitted_review = client.post(
        "/api/v1/reviews/queue",
        headers={"X-API-Key": "operator-key"},
        json={
            "session_id": session_id,
            "action_payload": {"action_type": "click"},
            "confidence": 0.2,
            "reason": "low-confidence candidate",
        },
    )
    assert submitted_review.status_code == 200

    evaluated_policy = client.post(
        "/api/v1/policy/decisions/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={
            "actor_id": "agent-meter",
            "site_id": "site-meter",
            "region_allowed": True,
            "has_authorization": True,
            "risk_score": 0.1,
            "action": "click",
        },
    )
    assert evaluated_policy.status_code == 200

    evaluated_flag = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "metered-flag", "subject_key": "subject-1"},
    )
    assert evaluated_flag.status_code == 200

    summary = client.get(
        "/api/v1/usage/metering/summary",
        headers={"X-API-Key": "admin-key"},
        params={"tenant_id": "tenant-op"},
    )
    assert summary.status_code == 200
    summary_payload = summary.json()
    dimensions = summary_payload["dimensions"]
    assert dimensions["api_request"] >= 1.0
    assert dimensions["session_create"] >= 1.0
    assert dimensions["session_step"] >= 1.0
    assert dimensions["async_job_submit"] >= 1.0
    assert dimensions["review_queue_submit"] >= 1.0
    assert dimensions["policy_decision_evaluate"] >= 1.0
    assert dimensions["feature_flag_evaluate"] >= 1.0

    records = client.get(
        "/api/v1/usage/metering/records",
        headers={"X-API-Key": "admin-key"},
        params={"tenant_id": "tenant-op", "dimension": "session_create"},
    )
    assert records.status_code == 200
    assert records.json()["total"] >= 1


def test_usage_metering_routes_require_admin(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")

    client = TestClient(create_app())

    denied = client.get("/api/v1/usage/metering/summary", headers={"X-API-Key": "viewer-key"})
    assert denied.status_code == 403

    allowed = client.get("/api/v1/usage/metering/summary", headers={"X-API-Key": "admin-key"})
    assert allowed.status_code == 200


def test_usage_metering_legacy_routes_emit_deprecation_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")

    client = TestClient(create_app())

    records = client.get("/usage/metering/records", headers={"X-API-Key": "admin-key"})
    assert records.status_code == 200
    assert records.headers.get("Deprecation") == "true"

    summary = client.get("/usage/metering/summary", headers={"X-API-Key": "admin-key"})
    assert summary.status_code == 200
    assert summary.headers.get("Deprecation") == "true"


def test_json_file_usage_metering_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "usage-metering.json"
    store = JsonFileUsageMeteringStore(str(store_path))
    metering = TenantUsageMetering(store=store)

    metering.record(tenant_id="tenant-a", dimension="api_request", units=2.0)
    metering.record(tenant_id="tenant-a", dimension="session_create", units=1.0)

    reloaded = TenantUsageMetering(store=store)
    records = reloaded.list_records(tenant_id="tenant-a")
    summary = reloaded.summarize(tenant_id="tenant-a")

    assert len(records) == 2
    assert summary["dimensions"]["api_request"] == 2.0
    assert summary["dimensions"]["session_create"] == 1.0
