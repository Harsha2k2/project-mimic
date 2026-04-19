from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.managed_connectors import (
    JsonFileManagedConnectorStore,
    PartnerIntegrationService,
)


def test_managed_connectors_template_connector_and_health_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    template = client.post(
        "/api/v1/connectors/templates/slack-alerts",
        headers={"X-API-Key": "admin-key"},
        json={
            "provider": "slack",
            "category": "notifications",
            "auth_type": "api_key",
            "required_config_keys": ["webhook_url"],
            "optional_config_keys": ["channel"],
            "default_scopes": ["chat:write"],
            "webhook_supported": True,
            "rate_limit_per_minute": 300,
        },
    )
    assert template.status_code == 200

    created = client.post(
        "/api/v1/connectors/instances/slack-primary",
        headers={"X-API-Key": "operator-key"},
        json={
            "template_id": "slack-alerts",
            "name": "Slack Primary",
            "config": {"webhook_url": "https://hooks.slack.com/services/abc"},
            "enabled": True,
        },
    )
    assert created.status_code == 200

    health = client.post(
        "/api/v1/connectors/instances/slack-primary/health-check",
        headers={"X-API-Key": "operator-key"},
    )
    assert health.status_code == 200
    assert health.json()["healthy"] is True

    listing = client.get(
        "/api/v1/connectors/instances",
        headers={"X-API-Key": "operator-key"},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    fetched = client.get(
        "/api/v1/connectors/instances/slack-primary",
        headers={"X-API-Key": "operator-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["connector_id"] == "slack-primary"


def test_managed_connectors_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key,viewer-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator,viewer-key:viewer")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a,viewer-key:tenant-a")

    client = TestClient(create_app())

    forbidden_template = client.post(
        "/api/v1/connectors/templates/slack-alerts",
        headers={"X-API-Key": "operator-key"},
        json={
            "provider": "slack",
            "category": "notifications",
            "auth_type": "api_key",
            "required_config_keys": ["webhook_url"],
            "rate_limit_per_minute": 100,
        },
    )
    assert forbidden_template.status_code == 403

    seed_template = client.post(
        "/api/v1/connectors/templates/slack-alerts",
        headers={"X-API-Key": "admin-key"},
        json={
            "provider": "slack",
            "category": "notifications",
            "auth_type": "api_key",
            "required_config_keys": ["webhook_url"],
            "rate_limit_per_minute": 100,
        },
    )
    assert seed_template.status_code == 200

    legacy_create = client.post(
        "/connectors/instances/slack-primary",
        headers={"X-API-Key": "operator-key"},
        json={
            "template_id": "slack-alerts",
            "name": "Slack Primary",
            "config": {"webhook_url": "https://hooks.slack.com/services/abc"},
            "enabled": False,
        },
    )
    assert legacy_create.status_code == 200
    assert legacy_create.headers.get("Deprecation") == "true"

    forbidden_list = client.get(
        "/api/v1/connectors/templates",
        headers={"X-API-Key": "viewer-key"},
    )
    assert forbidden_list.status_code == 403

    legacy_health = client.post(
        "/connectors/instances/slack-primary/health-check",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_health.status_code == 200
    assert legacy_health.headers.get("Deprecation") == "true"
    assert legacy_health.json()["healthy"] is False


def test_json_file_managed_connector_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "managed-connectors.json"
    service = PartnerIntegrationService(store=JsonFileManagedConnectorStore(str(store_path)))

    service.upsert_template(
        template_id="slack-alerts",
        provider="slack",
        category="notifications",
        auth_type="api_key",
        required_config_keys=["webhook_url"],
        optional_config_keys=["channel"],
        default_scopes=["chat:write"],
        webhook_supported=True,
        rate_limit_per_minute=120,
    )
    service.create_connector(
        tenant_id="tenant-a",
        connector_id="slack-primary",
        template_id="slack-alerts",
        name="Slack Primary",
        config={"webhook_url": "https://hooks.slack.com/services/abc"},
        enabled=True,
    )

    health = service.check_connector_health(tenant_id="tenant-a", connector_id="slack-primary")
    assert health["healthy"] is True

    reloaded = PartnerIntegrationService(store=JsonFileManagedConnectorStore(str(store_path)))
    templates = reloaded.list_templates()
    connectors = reloaded.list_connectors(tenant_id="tenant-a")

    assert len(templates) == 1
    assert len(connectors) == 1
