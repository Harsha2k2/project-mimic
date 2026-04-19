from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_drift_sample_ingest_and_status_query() -> None:
    client = TestClient(create_app())

    ingested = client.post(
        "/api/v1/drift/samples",
        json={"stream_id": "model-a", "metric_name": "grounding_accuracy", "value": 0.92},
    )
    assert ingested.status_code == 200
    payload = ingested.json()
    assert payload["baseline_samples"] == 1
    assert payload["alert_active"] is False

    status = client.get(
        "/api/v1/drift/status",
        params={"stream_id": "model-a", "metric_name": "grounding_accuracy"},
    )
    assert status.status_code == 200
    assert status.json()["stream_id"] == "model-a"


def test_drift_alert_activates_when_threshold_is_exceeded() -> None:
    client = TestClient(create_app())

    for _ in range(20):
        baseline = client.post(
            "/api/v1/drift/samples",
            json={
                "stream_id": "model-b",
                "metric_name": "logit_shift",
                "value": 1.0,
                "threshold": 0.2,
            },
        )
        assert baseline.status_code == 200

    drifted = client.post(
        "/api/v1/drift/samples",
        json={
            "stream_id": "model-b",
            "metric_name": "logit_shift",
            "value": 2.0,
            "threshold": 0.2,
        },
    )
    assert drifted.status_code == 200
    assert drifted.json()["alert_active"] is True

    alerts = client.get("/api/v1/drift/alerts")
    assert alerts.status_code == 200
    alerts_payload = alerts.json()
    assert alerts_payload["total"] >= 1
    assert any(item["stream_id"] == "model-b" for item in alerts_payload["items"])


def test_drift_status_returns_404_for_unknown_metric() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/drift/status",
        params={"stream_id": "missing", "metric_name": "missing"},
    )
    assert response.status_code == 404


def test_legacy_drift_routes_emit_deprecation_headers() -> None:
    client = TestClient(create_app())

    sampled = client.post(
        "/drift/samples",
        json={"stream_id": "legacy", "metric_name": "stability", "value": 0.5},
    )
    assert sampled.status_code == 200
    assert sampled.headers.get("Deprecation") == "true"

    status = client.get("/drift/status", params={"stream_id": "legacy", "metric_name": "stability"})
    assert status.status_code == 200
    assert status.headers.get("Deprecation") == "true"

    alerts = client.get("/drift/alerts")
    assert alerts.status_code == 200
    assert alerts.headers.get("Deprecation") == "true"
