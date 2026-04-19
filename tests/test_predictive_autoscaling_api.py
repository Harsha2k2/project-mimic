from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.predictive_autoscaling import (
    JsonFilePredictiveAutoscalingStore,
    PredictiveAutoscalingService,
)


def test_predictive_autoscaling_scale_up_flow() -> None:
    client = TestClient(create_app())

    upsert = client.post(
        "/api/v1/autoscaling/predictive/policies/pool-a",
        json={
            "resource_type": "worker",
            "resource_id": "bw-large",
            "min_replicas": 1,
            "max_replicas": 6,
            "scale_up_step": 2,
            "scale_down_step": 1,
            "queue_depth_target": 40.0,
            "latency_ms_target": 150.0,
            "lookback_window": 4,
            "cooldown_seconds": 0,
        },
        headers={"X-API-Key": "dev-key"},
    )
    assert upsert.status_code == 200

    for queue_depth, latency_ms in [(42.0, 160.0), (58.0, 190.0), (72.0, 240.0)]:
        signal = client.post(
            "/api/v1/autoscaling/predictive/signals",
            json={
                "policy_id": "pool-a",
                "queue_depth": queue_depth,
                "latency_ms": latency_ms,
            },
            headers={"X-API-Key": "dev-key"},
        )
        assert signal.status_code == 200

    recommendation = client.post(
        "/api/v1/autoscaling/predictive/recommend",
        json={"policy_id": "pool-a", "current_replicas": 2},
        headers={"X-API-Key": "dev-key"},
    )
    assert recommendation.status_code == 200
    recommendation_payload = recommendation.json()
    assert recommendation_payload["direction"] == "scale_up"
    assert recommendation_payload["desired_replicas"] == 4

    status = client.get(
        "/api/v1/autoscaling/predictive/status/pool-a",
        headers={"X-API-Key": "dev-key"},
    )
    assert status.status_code == 200
    assert status.json()["sample_count"] == 3

    policies = client.get(
        "/api/v1/autoscaling/predictive/policies",
        headers={"X-API-Key": "dev-key"},
    )
    assert policies.status_code == 200
    assert policies.json()["total"] == 1


def test_predictive_autoscaling_scale_down_respects_min_replicas() -> None:
    client = TestClient(create_app())

    upsert = client.post(
        "/api/v1/autoscaling/predictive/policies/model-a",
        json={
            "resource_type": "model",
            "resource_id": "planner-v2",
            "min_replicas": 2,
            "max_replicas": 8,
            "scale_up_step": 2,
            "scale_down_step": 2,
            "queue_depth_target": 100.0,
            "latency_ms_target": 400.0,
            "lookback_window": 3,
            "cooldown_seconds": 0,
        },
        headers={"X-API-Key": "dev-key"},
    )
    assert upsert.status_code == 200

    for queue_depth, latency_ms in [(60.0, 220.0), (45.0, 180.0), (30.0, 140.0)]:
        signal = client.post(
            "/api/v1/autoscaling/predictive/signals",
            json={
                "policy_id": "model-a",
                "queue_depth": queue_depth,
                "latency_ms": latency_ms,
            },
            headers={"X-API-Key": "dev-key"},
        )
        assert signal.status_code == 200

    recommendation = client.post(
        "/api/v1/autoscaling/predictive/recommend",
        json={"policy_id": "model-a", "current_replicas": 7},
        headers={"X-API-Key": "dev-key"},
    )
    assert recommendation.status_code == 200
    recommendation_payload = recommendation.json()
    assert recommendation_payload["direction"] == "scale_down"
    assert recommendation_payload["desired_replicas"] == 5

    bounded = client.post(
        "/api/v1/autoscaling/predictive/recommend",
        json={"policy_id": "model-a", "current_replicas": 2},
        headers={"X-API-Key": "dev-key"},
    )
    assert bounded.status_code == 200
    bounded_payload = bounded.json()
    assert bounded_payload["direction"] == "hold"
    assert bounded_payload["desired_replicas"] == 2


def test_predictive_autoscaling_roles_legacy_and_tenant_scope(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a,admin-key:tenant-a")

    client = TestClient(create_app())

    forbidden_policy_upsert = client.post(
        "/api/v1/autoscaling/predictive/policies/pool-a",
        json={
            "resource_type": "worker",
            "resource_id": "bw-small",
            "min_replicas": 1,
            "max_replicas": 4,
            "scale_up_step": 1,
            "scale_down_step": 1,
            "queue_depth_target": 20.0,
            "latency_ms_target": 120.0,
            "lookback_window": 3,
            "cooldown_seconds": 0,
        },
        headers={"X-API-Key": "operator-key"},
    )
    assert forbidden_policy_upsert.status_code == 403

    legacy_upsert = client.post(
        "/autoscaling/predictive/policies/pool-a",
        json={
            "resource_type": "worker",
            "resource_id": "bw-small",
            "min_replicas": 1,
            "max_replicas": 4,
            "scale_up_step": 1,
            "scale_down_step": 1,
            "queue_depth_target": 20.0,
            "latency_ms_target": 120.0,
            "lookback_window": 3,
            "cooldown_seconds": 0,
        },
        headers={"X-API-Key": "admin-key"},
    )
    assert legacy_upsert.status_code == 200
    assert legacy_upsert.headers.get("Deprecation") == "true"

    forbidden_signal = client.post(
        "/api/v1/autoscaling/predictive/signals",
        json={
            "policy_id": "pool-a",
            "queue_depth": 22.0,
            "latency_ms": 130.0,
        },
        headers={"X-API-Key": "viewer-key"},
    )
    assert forbidden_signal.status_code == 403

    legacy_signal = client.post(
        "/autoscaling/predictive/signals",
        json={
            "policy_id": "pool-a",
            "queue_depth": 24.0,
            "latency_ms": 140.0,
        },
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_signal.status_code == 200
    assert legacy_signal.headers.get("Deprecation") == "true"

    legacy_recommend = client.post(
        "/autoscaling/predictive/recommend",
        json={"policy_id": "pool-a", "current_replicas": 2},
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_recommend.status_code == 200
    assert legacy_recommend.headers.get("Deprecation") == "true"

    tenant_override = client.post(
        "/api/v1/autoscaling/predictive/recommend",
        json={"policy_id": "pool-a", "current_replicas": 2, "tenant_id": "tenant-b"},
        headers={"X-API-Key": "operator-key"},
    )
    assert tenant_override.status_code == 403


def test_predictive_autoscaling_json_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "predictive-autoscaling.json"

    service = PredictiveAutoscalingService(store=JsonFilePredictiveAutoscalingStore(str(store_path)))
    service.upsert_policy(
        policy_id="pool-a",
        tenant_id="tenant-a",
        resource_type="worker",
        resource_id="bw-large",
        min_replicas=1,
        max_replicas=5,
        scale_up_step=1,
        scale_down_step=1,
        queue_depth_target=50.0,
        latency_ms_target=200.0,
        lookback_window=3,
        cooldown_seconds=0,
    )
    service.ingest_signal(
        policy_id="pool-a",
        tenant_id="tenant-a",
        queue_depth=70.0,
        latency_ms=260.0,
    )
    service.ingest_signal(
        policy_id="pool-a",
        tenant_id="tenant-a",
        queue_depth=85.0,
        latency_ms=300.0,
    )
    recommendation = service.recommend(
        policy_id="pool-a",
        tenant_id="tenant-a",
        current_replicas=2,
    )
    assert recommendation["desired_replicas"] == 3

    reloaded = PredictiveAutoscalingService(store=JsonFilePredictiveAutoscalingStore(str(store_path)))
    policies = reloaded.list_policies(tenant_id="tenant-a")
    status = reloaded.status(policy_id="pool-a", tenant_id="tenant-a")

    assert len(policies) == 1
    assert status is not None
    assert status["sample_count"] == 2
