from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_submit_and_poll_async_job_flow() -> None:
    client = TestClient(create_app())

    submitted = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "long-running-evaluation",
            "input": {"session_id": "session-1"},
            "idempotency_key": "job-key-1",
        },
    )
    assert submitted.status_code == 200
    submitted_payload = submitted.json()
    job_id = submitted_payload["job"]["job_id"]
    assert submitted_payload["job"]["status"] == "queued"

    polled = client.get(f"/api/v1/jobs/{job_id}")
    assert polled.status_code == 200
    polled_payload = polled.json()
    assert polled_payload["job_id"] == job_id
    assert polled_payload["status"] == "queued"


def test_submit_async_job_respects_idempotency_key() -> None:
    client = TestClient(create_app())

    first = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "report-build",
            "input": {"report_id": "r-1"},
            "idempotency_key": "dup-key",
        },
    )
    second = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "report-build",
            "input": {"report_id": "r-1"},
            "idempotency_key": "dup-key",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]


def test_cancel_async_job_transitions_to_canceled() -> None:
    client = TestClient(create_app())

    submitted = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "cancelable",
            "input": {},
            "idempotency_key": "cancel-key",
        },
    )
    assert submitted.status_code == 200
    job_id = submitted.json()["job"]["job_id"]

    canceled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert canceled.status_code == 200
    canceled_payload = canceled.json()
    assert canceled_payload["canceled"] is True
    assert canceled_payload["job"]["status"] == "canceled"

    polled = client.get(f"/api/v1/jobs/{job_id}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "canceled"

    second_cancel = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert second_cancel.status_code == 409


def test_legacy_async_job_routes_emit_deprecation_headers() -> None:
    client = TestClient(create_app())

    submitted = client.post(
        "/jobs",
        json={
            "job_type": "legacy-job",
            "input": {},
            "idempotency_key": "legacy-key",
        },
    )
    assert submitted.status_code == 200
    assert submitted.headers.get("Deprecation") == "true"
    job_id = submitted.json()["job"]["job_id"]

    polled = client.get(f"/jobs/{job_id}")
    assert polled.status_code == 200
    assert polled.headers.get("Deprecation") == "true"

    canceled = client.post(f"/jobs/{job_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.headers.get("Deprecation") == "true"
