from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.feature_flags import FeatureFlagService, JsonFileFeatureFlagStore


def test_feature_flag_management_and_progressive_evaluation(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={
            "flag_key": "new-retrier",
            "description": "Progressive retry strategy",
            "enabled": True,
            "rollout_percentage": 0,
            "subject_allowlist": ["beta-user"],
        },
    )
    assert created.status_code == 200
    assert created.json()["flag_key"] == "new-retrier"

    allowlisted = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "new-retrier", "subject_key": "beta-user"},
    )
    assert allowlisted.status_code == 200
    assert allowlisted.json()["enabled"] is True
    assert allowlisted.json()["reason"] == "subject_allowlisted"

    non_allowlisted = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "new-retrier", "subject_key": "regular-user"},
    )
    assert non_allowlisted.status_code == 200
    assert non_allowlisted.json()["enabled"] is False
    assert non_allowlisted.json()["reason"] == "rollout_excluded"

    updated = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={
            "flag_key": "new-retrier",
            "description": "Progressive retry strategy",
            "enabled": True,
            "rollout_percentage": 100,
        },
    )
    assert updated.status_code == 200

    rolled_out = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "new-retrier", "subject_key": "regular-user"},
    )
    assert rolled_out.status_code == 200
    assert rolled_out.json()["enabled"] is True

    listed = client.get("/api/v1/feature-flags", headers={"X-API-Key": "admin-key"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    fetched = client.get("/api/v1/feature-flags/new-retrier", headers={"X-API-Key": "admin-key"})
    assert fetched.status_code == 200

    deleted = client.delete("/api/v1/feature-flags/new-retrier", headers={"X-API-Key": "admin-key"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = client.get("/api/v1/feature-flags/new-retrier", headers={"X-API-Key": "admin-key"})
    assert missing.status_code == 404


def test_feature_flag_routes_require_expected_roles(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")

    client = TestClient(create_app())

    forbidden_create = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "f1", "enabled": True, "rollout_percentage": 10},
    )
    assert forbidden_create.status_code == 403

    created = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={"flag_key": "f1", "enabled": True, "rollout_percentage": 10},
    )
    assert created.status_code == 200

    forbidden_list = client.get("/api/v1/feature-flags", headers={"X-API-Key": "viewer-key"})
    assert forbidden_list.status_code == 403

    allowed_eval = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "f1", "subject_key": "s1"},
    )
    assert allowed_eval.status_code == 200


def test_feature_flag_evaluation_tenant_scope_is_enforced(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-b")

    client = TestClient(create_app())

    created = client.post(
        "/api/v1/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={
            "flag_key": "tenant-flag",
            "enabled": True,
            "rollout_percentage": 100,
            "tenant_allowlist": ["tenant-a"],
        },
    )
    assert created.status_code == 200

    denied = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "tenant-flag", "subject_key": "s1"},
    )
    assert denied.status_code == 200
    assert denied.json()["enabled"] is False
    assert denied.json()["reason"] == "tenant_not_allowlisted"

    override_denied = client.post(
        "/api/v1/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "tenant-flag", "subject_key": "s1", "tenant_id": "tenant-a"},
    )
    assert override_denied.status_code == 403


def test_feature_flag_legacy_routes_emit_deprecation_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")

    client = TestClient(create_app())

    created = client.post(
        "/feature-flags",
        headers={"X-API-Key": "admin-key"},
        json={"flag_key": "legacy-flag", "enabled": True, "rollout_percentage": 50},
    )
    assert created.status_code == 200
    assert created.headers.get("Deprecation") == "true"

    listed = client.get("/feature-flags", headers={"X-API-Key": "admin-key"})
    assert listed.status_code == 200
    assert listed.headers.get("Deprecation") == "true"

    fetched = client.get("/feature-flags/legacy-flag", headers={"X-API-Key": "admin-key"})
    assert fetched.status_code == 200
    assert fetched.headers.get("Deprecation") == "true"

    evaluated = client.post(
        "/feature-flags/evaluate",
        headers={"X-API-Key": "operator-key"},
        json={"flag_key": "legacy-flag", "subject_key": "user-1"},
    )
    assert evaluated.status_code == 200
    assert evaluated.headers.get("Deprecation") == "true"

    deleted = client.delete("/feature-flags/legacy-flag", headers={"X-API-Key": "admin-key"})
    assert deleted.status_code == 200
    assert deleted.headers.get("Deprecation") == "true"


def test_json_file_feature_flag_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "feature-flags.json"
    store = JsonFileFeatureFlagStore(str(store_path))
    service = FeatureFlagService(store=store)

    service.upsert(
        flag_key="fast-path",
        description="Enable fast-path execution",
        enabled=True,
        rollout_percentage=25,
        tenant_allowlist=["tenant-a"],
        subject_allowlist=["subject-1"],
    )

    reloaded = FeatureFlagService(store=store)
    fetched = reloaded.get(flag_key="fast-path")

    assert fetched["flag_key"] == "fast-path"
    assert fetched["rollout_percentage"] == 25
    assert fetched["tenant_allowlist"] == ["tenant-a"]
