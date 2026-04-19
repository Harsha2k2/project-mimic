from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.site_pack_registry import JsonFileSitePackRegistryStore, SitePackRegistry


def test_site_pack_registry_register_list_promote_and_runtime_mapping(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    monkeypatch.setenv("SITE_PACK_ACTIVE_CHANNEL", "dev")
    monkeypatch.setenv("SITE_PACK_AUTO_APPLY", "true")

    client = TestClient(create_app())

    registered = client.post(
        "/api/v1/site-packs/register",
        headers={"X-API-Key": "admin-key"},
        json={
            "pack_id": "site-a-pack",
            "version": "v1",
            "strategy_class": "project_mimic.orchestrator.strategy.OrchestrationStrategy",
            "artifact_uri": "s3://site-packs/site-a/v1",
            "site_ids": ["site-a"],
            "metadata": {"author": "ops"},
        },
    )
    assert registered.status_code == 200
    registered_payload = registered.json()
    assert registered_payload["pack_id"] == "site-a-pack"
    assert registered_payload["version"] == "v1"
    assert registered_payload["site_ids"] == ["site-a"]

    versions = client.get(
        "/api/v1/site-packs/versions",
        headers={"X-API-Key": "admin-key"},
        params={"pack_id": "site-a-pack"},
    )
    assert versions.status_code == 200
    assert versions.json()["total"] == 1

    promoted = client.post(
        "/api/v1/site-packs/channels/dev/promote",
        headers={"X-API-Key": "admin-key"},
        json={"pack_id": "site-a-pack", "version": "v1"},
    )
    assert promoted.status_code == 200
    promoted_payload = promoted.json()["assignment"]
    assert promoted_payload["channel"] == "dev"
    assert promoted_payload["applied_site_ids"] == ["site-a"]

    channels = client.get(
        "/api/v1/site-packs/channels",
        headers={"X-API-Key": "admin-key"},
    )
    assert channels.status_code == 200
    assert channels.json()["channels"]["dev"]["version"] == "v1"

    runtime_mapping = client.get(
        "/api/v1/site-packs/runtime/strategies",
        headers={"X-API-Key": "admin-key"},
    )
    assert runtime_mapping.status_code == 200
    mapping_payload = runtime_mapping.json()["mappings"]
    assert mapping_payload["site-a"] == "project_mimic.orchestrator.strategy.OrchestrationStrategy"


def test_site_pack_promotion_fails_for_unresolvable_strategy_class(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    monkeypatch.setenv("SITE_PACK_ACTIVE_CHANNEL", "dev")
    monkeypatch.setenv("SITE_PACK_AUTO_APPLY", "true")

    client = TestClient(create_app())

    registered = client.post(
        "/api/v1/site-packs/register",
        headers={"X-API-Key": "admin-key"},
        json={
            "pack_id": "site-b-pack",
            "version": "v1",
            "strategy_class": "project_mimic.orchestrator.strategy.DoesNotExist",
            "artifact_uri": "s3://site-packs/site-b/v1",
            "site_ids": ["site-b"],
        },
    )
    assert registered.status_code == 200

    promoted = client.post(
        "/api/v1/site-packs/channels/dev/promote",
        headers={"X-API-Key": "admin-key"},
        json={"pack_id": "site-b-pack", "version": "v1"},
    )
    assert promoted.status_code == 400


def test_site_pack_routes_require_admin_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/site-packs/register",
        headers={"X-API-Key": "viewer-key"},
        json={
            "pack_id": "legacy-pack",
            "version": "v1",
            "strategy_class": "project_mimic.orchestrator.strategy.OrchestrationStrategy",
            "artifact_uri": "s3://site-packs/legacy/v1",
            "site_ids": ["legacy-site"],
        },
    )
    assert forbidden.status_code == 403

    legacy_register = client.post(
        "/site-packs/register",
        headers={"X-API-Key": "admin-key"},
        json={
            "pack_id": "legacy-pack",
            "version": "v1",
            "strategy_class": "project_mimic.orchestrator.strategy.OrchestrationStrategy",
            "artifact_uri": "s3://site-packs/legacy/v1",
            "site_ids": ["legacy-site"],
        },
    )
    assert legacy_register.status_code == 200
    assert legacy_register.headers.get("Deprecation") == "true"

    legacy_versions = client.get("/site-packs/versions", headers={"X-API-Key": "admin-key"})
    assert legacy_versions.status_code == 200
    assert legacy_versions.headers.get("Deprecation") == "true"

    legacy_promote = client.post(
        "/site-packs/channels/dev/promote",
        headers={"X-API-Key": "admin-key"},
        json={"pack_id": "legacy-pack", "version": "v1"},
    )
    assert legacy_promote.status_code == 200
    assert legacy_promote.headers.get("Deprecation") == "true"

    legacy_apply = client.post("/site-packs/channels/dev/apply", headers={"X-API-Key": "admin-key"})
    assert legacy_apply.status_code == 200
    assert legacy_apply.headers.get("Deprecation") == "true"

    legacy_channels = client.get("/site-packs/channels", headers={"X-API-Key": "admin-key"})
    assert legacy_channels.status_code == 200
    assert legacy_channels.headers.get("Deprecation") == "true"

    legacy_runtime = client.get("/site-packs/runtime/strategies", headers={"X-API-Key": "admin-key"})
    assert legacy_runtime.status_code == 200
    assert legacy_runtime.headers.get("Deprecation") == "true"


def test_json_file_site_pack_registry_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "site-pack-registry.json"
    store = JsonFileSitePackRegistryStore(str(store_path))
    registry = SitePackRegistry(store=store)

    registry.register_version(
        pack_id="pack-a",
        version="v2",
        strategy_class="project_mimic.orchestrator.strategy.OrchestrationStrategy",
        artifact_uri="s3://site-packs/pack-a/v2",
        site_ids=["site-a", "site-b"],
        metadata={"checksum": "abc"},
    )
    registry.promote(channel="canary", pack_id="pack-a", version="v2")

    reloaded = SitePackRegistry(store=store)
    versions = reloaded.list_versions(pack_id="pack-a")
    channels = reloaded.list_channels()

    assert len(versions) == 1
    assert versions[0]["version"] == "v2"
    assert versions[0]["site_ids"] == ["site-a", "site-b"]
    assert channels["canary"] is not None
    assert channels["canary"]["version"] == "v2"
