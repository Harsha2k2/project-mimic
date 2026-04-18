from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.observability import InMemoryMetrics


def test_metrics_snapshot_contains_stable_fields() -> None:
    metrics = InMemoryMetrics()
    metrics.record("/api/v1/sessions", 200, 10.0)
    metrics.record("/api/v1/sessions", 200, 20.0)
    metrics.record("/api/v1/sessions", 500, 40.0)
    metrics.record_feature_result(
        "session.step",
        success=True,
        trace_id="trace-1",
        goal="find flights",
        action_type="click",
    )

    snapshot = metrics.snapshot()

    assert "requests" in snapshot
    assert "status_codes" in snapshot
    assert "average_latency_ms" in snapshot
    assert "latency_percentiles_ms" in snapshot
    assert "feature_success_rates" in snapshot
    assert "dashboards" in snapshot
    assert "goal_action_correlation" in snapshot
    assert "trace_links" in snapshot

    percentiles = snapshot["latency_percentiles_ms"]["/api/v1/sessions"]
    assert set(percentiles.keys()) == {"p95", "p99", "count"}
    assert percentiles["p95"] >= 0.0
    assert percentiles["p99"] >= 0.0


def test_api_metrics_endpoint_exposes_trace_and_dashboard_fields() -> None:
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/sessions",
        json={"goal": "trace goal", "max_steps": 2},
        headers={"X-Request-ID": "trace-goal-1"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    stepped = client.post(
        f"/api/v1/sessions/{session_id}/step",
        json={"action_type": "click", "target": "search"},
        headers={"X-Request-ID": "trace-goal-2"},
    )
    assert stepped.status_code == 200

    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()

    assert "latency_percentiles_ms" in payload
    assert "feature_success_rates" in payload
    assert "dashboards" in payload
    assert "goal_action_correlation" in payload
    assert "traces" in payload

    assert "api" in payload["traces"]
    assert "orchestrator" in payload["traces"]
    assert payload["traces"]["api"]["span_count"] >= 1
