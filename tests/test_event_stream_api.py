from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_events_stream_returns_sse_for_session_create() -> None:
    client = TestClient(create_app())

    created = client.post("/api/v1/sessions", json={"goal": "stream-create", "max_steps": 2})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    stream = client.get("/api/v1/events/stream?after_id=0&max_events=20&wait_seconds=0")
    assert stream.status_code == 200
    assert stream.headers.get("content-type", "").startswith("text/event-stream")
    assert "event: session.create" in stream.text
    assert session_id in stream.text


def test_events_stream_filters_by_event_type() -> None:
    client = TestClient(create_app())

    client.post("/api/v1/sessions", json={"goal": "stream-filter", "max_steps": 2})
    submitted = client.post(
        "/api/v1/jobs",
        json={"job_type": "filter-job", "input": {}, "idempotency_key": "stream-filter-key"},
    )
    assert submitted.status_code == 200

    stream = client.get(
        "/api/v1/events/stream?after_id=0&max_events=20&wait_seconds=0&event_type=async_job.submit"
    )
    assert stream.status_code == 200
    assert "event: async_job.submit" in stream.text
    assert "event: session.create" not in stream.text


def test_events_stream_is_tenant_scoped(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "key-a,key-b")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "key-a:operator,key-b:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "key-a:tenant-a,key-b:tenant-b")

    client = TestClient(create_app())

    tenant_a_session = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "key-a"},
        json={"goal": "tenant-a", "max_steps": 2},
    )
    tenant_b_session = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "key-b"},
        json={"goal": "tenant-b", "max_steps": 2},
    )
    assert tenant_a_session.status_code == 200
    assert tenant_b_session.status_code == 200

    a_id = tenant_a_session.json()["session_id"]
    b_id = tenant_b_session.json()["session_id"]

    stream_a = client.get(
        "/api/v1/events/stream?after_id=0&max_events=20&wait_seconds=0",
        headers={"X-API-Key": "key-a"},
    )
    assert stream_a.status_code == 200
    assert a_id in stream_a.text
    assert b_id not in stream_a.text


def test_legacy_events_stream_emits_deprecation_headers() -> None:
    client = TestClient(create_app())
    client.post("/api/v1/sessions", json={"goal": "legacy-stream", "max_steps": 2})

    response = client.get("/events/stream?after_id=0&max_events=20&wait_seconds=0")
    assert response.status_code == 200
    assert response.headers.get("Deprecation") == "true"
