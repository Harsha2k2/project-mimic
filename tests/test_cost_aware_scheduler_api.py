from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.cost_aware_scheduler import (
    CostAwareScheduler,
    JsonFileCostAwareSchedulerStore,
)


def test_cost_aware_scheduler_profile_and_route_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-admin,operator-key:tenant-op")

    client = TestClient(create_app())

    model_a = client.post(
        "/api/v1/scheduler/cost-aware/models/planner-cheap",
        headers={"X-API-Key": "admin-key"},
        json={
            "model_id": "planner-v1",
            "region": "us-east",
            "cost_per_1k_tokens": 0.8,
            "latency_ms": 180,
            "queue_depth": 5,
            "quality_score": 0.92,
        },
    )
    assert model_a.status_code == 200

    model_b = client.post(
        "/api/v1/scheduler/cost-aware/models/planner-fast",
        headers={"X-API-Key": "admin-key"},
        json={
            "model_id": "planner-v2",
            "region": "eu-west",
            "cost_per_1k_tokens": 1.6,
            "latency_ms": 95,
            "queue_depth": 2,
            "quality_score": 0.96,
        },
    )
    assert model_b.status_code == 200

    worker_a = client.post(
        "/api/v1/scheduler/cost-aware/workers/worker-cheap",
        headers={"X-API-Key": "admin-key"},
        json={
            "worker_pool": "bw-small",
            "region": "us-east",
            "cost_per_minute": 0.12,
            "latency_ms": 210,
            "queue_depth": 8,
            "reliability_score": 0.93,
        },
    )
    assert worker_a.status_code == 200

    worker_b = client.post(
        "/api/v1/scheduler/cost-aware/workers/worker-fast",
        headers={"X-API-Key": "admin-key"},
        json={
            "worker_pool": "bw-large",
            "region": "eu-west",
            "cost_per_minute": 0.36,
            "latency_ms": 90,
            "queue_depth": 3,
            "reliability_score": 0.97,
        },
    )
    assert worker_b.status_code == 200

    models = client.get("/api/v1/scheduler/cost-aware/models", headers={"X-API-Key": "admin-key"})
    assert models.status_code == 200
    assert models.json()["total"] == 2

    workers = client.get("/api/v1/scheduler/cost-aware/workers", headers={"X-API-Key": "admin-key"})
    assert workers.status_code == 200
    assert workers.json()["total"] == 2

    model_route_cost = client.post(
        "/api/v1/scheduler/cost-aware/route/model",
        headers={"X-API-Key": "operator-key"},
        json={"objective": "min_cost"},
    )
    assert model_route_cost.status_code == 200
    model_cost_payload = model_route_cost.json()
    assert model_cost_payload["route_type"] == "model"
    assert model_cost_payload["selected_candidate"] == "planner-cheap"

    model_route_latency = client.post(
        "/api/v1/scheduler/cost-aware/route/model",
        headers={"X-API-Key": "operator-key"},
        json={"objective": "low_latency"},
    )
    assert model_route_latency.status_code == 200
    assert model_route_latency.json()["selected_candidate"] == "planner-fast"

    worker_route_cost = client.post(
        "/api/v1/scheduler/cost-aware/route/worker",
        headers={"X-API-Key": "operator-key"},
        json={"objective": "min_cost"},
    )
    assert worker_route_cost.status_code == 200
    assert worker_route_cost.json()["selected_candidate"] == "worker-cheap"

    worker_route_latency = client.post(
        "/api/v1/scheduler/cost-aware/route/worker",
        headers={"X-API-Key": "operator-key"},
        json={"objective": "low_latency"},
    )
    assert worker_route_latency.status_code == 200
    assert worker_route_latency.json()["selected_candidate"] == "worker-fast"


def test_cost_aware_scheduler_roles_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-op,admin-key:tenant-admin")

    client = TestClient(create_app())

    forbidden_upsert = client.post(
        "/api/v1/scheduler/cost-aware/models/planner-a",
        headers={"X-API-Key": "operator-key"},
        json={
            "model_id": "planner-v1",
            "region": "us-east",
            "cost_per_1k_tokens": 1.0,
            "latency_ms": 120,
            "queue_depth": 1,
            "quality_score": 0.9,
        },
    )
    assert forbidden_upsert.status_code == 403

    seed = client.post(
        "/api/v1/scheduler/cost-aware/models/planner-a",
        headers={"X-API-Key": "admin-key"},
        json={
            "model_id": "planner-v1",
            "region": "us-east",
            "cost_per_1k_tokens": 1.0,
            "latency_ms": 120,
            "queue_depth": 1,
            "quality_score": 0.9,
        },
    )
    assert seed.status_code == 200

    forbidden_route = client.post(
        "/api/v1/scheduler/cost-aware/route/model",
        headers={"X-API-Key": "viewer-key"},
        json={"objective": "balanced"},
    )
    assert forbidden_route.status_code == 403

    legacy_upsert = client.post(
        "/scheduler/cost-aware/models/planner-a",
        headers={"X-API-Key": "admin-key"},
        json={
            "model_id": "planner-v1",
            "region": "us-east",
            "cost_per_1k_tokens": 1.0,
            "latency_ms": 120,
            "queue_depth": 1,
            "quality_score": 0.9,
        },
    )
    assert legacy_upsert.status_code == 200
    assert legacy_upsert.headers.get("Deprecation") == "true"

    legacy_route = client.post(
        "/scheduler/cost-aware/route/model",
        headers={"X-API-Key": "operator-key"},
        json={"objective": "balanced"},
    )
    assert legacy_route.status_code == 200
    assert legacy_route.headers.get("Deprecation") == "true"

    tenant_override = client.post(
        "/api/v1/scheduler/cost-aware/route/model",
        headers={"X-API-Key": "operator-key"},
        json={"objective": "balanced", "tenant_id": "other-tenant"},
    )
    assert tenant_override.status_code == 403


def test_json_file_cost_aware_scheduler_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "cost-aware-scheduler.json"
    scheduler = CostAwareScheduler(store=JsonFileCostAwareSchedulerStore(str(store_path)))

    scheduler.upsert_model_profile(
        candidate_id="planner-cheap",
        model_id="planner-v1",
        region="us-east",
        cost_per_1k_tokens=0.8,
        latency_ms=180,
        queue_depth=4,
        quality_score=0.91,
    )
    scheduler.upsert_worker_profile(
        candidate_id="worker-cheap",
        worker_pool="bw-small",
        region="us-east",
        cost_per_minute=0.10,
        latency_ms=200,
        queue_depth=7,
        reliability_score=0.93,
    )

    reloaded = CostAwareScheduler(store=JsonFileCostAwareSchedulerStore(str(store_path)))
    model_profiles = reloaded.list_model_profiles()
    worker_profiles = reloaded.list_worker_profiles()
    model_route = reloaded.schedule_model(tenant_id="tenant-op", objective="min_cost")
    worker_route = reloaded.schedule_worker(tenant_id="tenant-op", objective="min_cost")

    assert len(model_profiles) == 1
    assert len(worker_profiles) == 1
    assert model_route["selected_candidate"] == "planner-cheap"
    assert worker_route["selected_candidate"] == "worker-cheap"
