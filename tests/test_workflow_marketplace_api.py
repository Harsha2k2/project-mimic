from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.workflow_marketplace import (
    JsonFileWorkflowMarketplaceStore,
    WorkflowMarketplaceService,
)


def test_workflow_marketplace_recipe_install_run_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    recipe = client.post(
        "/api/v1/workflows/marketplace/recipes/browser-failover",
        headers={"X-API-Key": "admin-key"},
        json={
            "title": "Browser Worker Failover",
            "category": "reliability",
            "description": "Fail over browser workers when latency spikes",
            "steps": [
                {
                    "action": "check.metrics",
                    "description": "Inspect p95 latency",
                    "parameters": {"metric": "worker_latency_p95"},
                },
                {
                    "action": "failover.execute",
                    "description": "Execute failover",
                    "parameters": {"target_region": "us-west"},
                },
            ],
            "tags": ["failover", "reliability"],
            "min_role": "operator",
            "version": "1.2.0",
            "published": True,
        },
    )
    assert recipe.status_code == 200

    install = client.post(
        "/api/v1/workflows/marketplace/installs/failover-us",
        headers={"X-API-Key": "operator-key"},
        json={
            "recipe_id": "browser-failover",
            "parameters": {"region": "us-west"},
            "enabled": True,
        },
    )
    assert install.status_code == 200

    run = client.post(
        "/api/v1/workflows/marketplace/installs/failover-us/run",
        headers={"X-API-Key": "operator-key"},
        json={"initiated_by": "oncall-1", "dry_run": True},
    )
    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["status"] == "completed"
    assert run_payload["dry_run"] is True
    assert len(run_payload["step_results"]) == 2

    list_runs = client.get(
        "/api/v1/workflows/marketplace/runs",
        headers={"X-API-Key": "operator-key"},
    )
    assert list_runs.status_code == 200
    assert list_runs.json()["total"] >= 1


def test_workflow_marketplace_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key,viewer-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator,viewer-key:viewer")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a,viewer-key:tenant-a")

    client = TestClient(create_app())

    forbidden_recipe = client.post(
        "/api/v1/workflows/marketplace/recipes/browser-failover",
        headers={"X-API-Key": "operator-key"},
        json={
            "title": "Browser Worker Failover",
            "category": "reliability",
            "description": "Fail over browser workers when latency spikes",
            "steps": [{"action": "check.metrics", "description": "Inspect", "parameters": {}}],
            "tags": ["failover"],
            "min_role": "operator",
            "version": "1.0.0",
            "published": True,
        },
    )
    assert forbidden_recipe.status_code == 403

    seed_recipe = client.post(
        "/api/v1/workflows/marketplace/recipes/browser-failover",
        headers={"X-API-Key": "admin-key"},
        json={
            "title": "Browser Worker Failover",
            "category": "reliability",
            "description": "Fail over browser workers when latency spikes",
            "steps": [{"action": "check.metrics", "description": "Inspect", "parameters": {}}],
            "tags": ["failover"],
            "min_role": "operator",
            "version": "1.0.0",
            "published": True,
        },
    )
    assert seed_recipe.status_code == 200

    forbidden_install = client.post(
        "/api/v1/workflows/marketplace/installs/failover-us",
        headers={"X-API-Key": "viewer-key"},
        json={"recipe_id": "browser-failover", "parameters": {}, "enabled": True},
    )
    assert forbidden_install.status_code == 403

    legacy_install = client.post(
        "/workflows/marketplace/installs/failover-us",
        headers={"X-API-Key": "operator-key"},
        json={"recipe_id": "browser-failover", "parameters": {}, "enabled": True},
    )
    assert legacy_install.status_code == 200
    assert legacy_install.headers.get("Deprecation") == "true"

    legacy_run = client.post(
        "/workflows/marketplace/installs/failover-us/run",
        headers={"X-API-Key": "operator-key"},
        json={"initiated_by": "legacy-op", "dry_run": False},
    )
    assert legacy_run.status_code == 200
    assert legacy_run.headers.get("Deprecation") == "true"


def test_json_file_workflow_marketplace_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "workflow-marketplace.json"
    service = WorkflowMarketplaceService(store=JsonFileWorkflowMarketplaceStore(str(store_path)))

    service.upsert_recipe(
        recipe_id="browser-failover",
        title="Browser Worker Failover",
        category="reliability",
        description="Fail over browser workers when latency spikes",
        steps=[{"action": "check.metrics", "description": "Inspect", "parameters": {}}],
        tags=["failover"],
        min_role="operator",
        version="1.0.0",
        published=True,
    )
    service.install_recipe(
        tenant_id="tenant-a",
        recipe_id="browser-failover",
        install_id="failover-us",
        parameters={"region": "us-west"},
        enabled=True,
    )

    run = service.run_install(
        tenant_id="tenant-a",
        install_id="failover-us",
        initiated_by="oncall-1",
        dry_run=True,
    )
    assert run["status"] == "completed"

    reloaded = WorkflowMarketplaceService(store=JsonFileWorkflowMarketplaceStore(str(store_path)))
    recipes = reloaded.list_recipes()
    installs = reloaded.list_installs(tenant_id="tenant-a")

    assert len(recipes) == 1
    assert len(installs) == 1
