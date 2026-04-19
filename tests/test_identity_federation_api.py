from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.identity_federation import (
    EnterpriseIdentityFederationService,
    JsonFileIdentityFederationStore,
)


def test_identity_federation_oidc_scim_and_auth_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    provider = client.post(
        "/api/v1/identity/providers/okta",
        headers={"X-API-Key": "admin-key"},
        json={
            "protocol": "oidc",
            "issuer": "https://idp.example.com",
            "client_id": "project-mimic",
            "metadata_url": "https://idp.example.com/.well-known/openid-configuration",
            "authorization_endpoint": "https://idp.example.com/oauth2/v1/authorize",
            "token_endpoint": "https://idp.example.com/oauth2/v1/token",
            "jwks_uri": "https://idp.example.com/oauth2/v1/keys",
            "enabled": True,
            "default_role": "viewer",
        },
    )
    assert provider.status_code == 200

    user = client.post(
        "/api/v1/identity/scim/users/u123",
        headers={"X-API-Key": "operator-key"},
        json={
            "email": "alice@example.com",
            "display_name": "Alice",
            "active": True,
            "role": "operator",
        },
    )
    assert user.status_code == 200

    group = client.post(
        "/api/v1/identity/scim/groups/g123",
        headers={"X-API-Key": "operator-key"},
        json={
            "display_name": "Ops",
            "members": ["u123"],
        },
    )
    assert group.status_code == 200

    authn = client.post(
        "/api/v1/identity/authenticate",
        headers={"X-API-Key": "operator-key"},
        json={
            "provider_id": "okta",
            "subject": "sub-1",
            "email": "alice@example.com",
            "groups": ["ops", "eng"],
        },
    )
    assert authn.status_code == 200
    authn_payload = authn.json()
    assert authn_payload["authenticated"] is True
    assert authn_payload["role"] == "operator"

    providers = client.get(
        "/api/v1/identity/providers",
        headers={"X-API-Key": "operator-key"},
    )
    assert providers.status_code == 200
    assert providers.json()["total"] == 1

    users = client.get(
        "/api/v1/identity/scim/users",
        headers={"X-API-Key": "operator-key"},
    )
    assert users.status_code == 200
    assert users.json()["total"] == 1


def test_identity_federation_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key,viewer-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator,viewer-key:viewer")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a,viewer-key:tenant-a")

    client = TestClient(create_app())

    forbidden_provider = client.post(
        "/api/v1/identity/providers/okta",
        headers={"X-API-Key": "operator-key"},
        json={
            "protocol": "oidc",
            "issuer": "https://idp.example.com",
            "client_id": "project-mimic",
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "enabled": True,
            "default_role": "viewer",
        },
    )
    assert forbidden_provider.status_code == 403

    seed_provider = client.post(
        "/api/v1/identity/providers/okta",
        headers={"X-API-Key": "admin-key"},
        json={
            "protocol": "oidc",
            "issuer": "https://idp.example.com",
            "client_id": "project-mimic",
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "enabled": True,
            "default_role": "viewer",
        },
    )
    assert seed_provider.status_code == 200

    forbidden_scim = client.post(
        "/api/v1/identity/scim/users/u123",
        headers={"X-API-Key": "viewer-key"},
        json={
            "email": "bob@example.com",
            "display_name": "Bob",
            "active": True,
            "role": "viewer",
        },
    )
    assert forbidden_scim.status_code == 403

    legacy_authn = client.post(
        "/identity/authenticate",
        headers={"X-API-Key": "operator-key"},
        json={
            "provider_id": "okta",
            "subject": "sub-legacy",
            "email": "legacy@example.com",
            "groups": ["ops"],
        },
    )
    assert legacy_authn.status_code == 200
    assert legacy_authn.headers.get("Deprecation") == "true"


def test_json_file_identity_federation_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "identity-federation.json"
    service = EnterpriseIdentityFederationService(store=JsonFileIdentityFederationStore(str(store_path)))

    service.upsert_provider(
        tenant_id="tenant-a",
        provider_id="okta",
        protocol="oidc",
        issuer="https://idp.example.com",
        client_id="project-mimic",
        metadata_url="https://idp.example.com/.well-known/openid-configuration",
        authorization_endpoint="https://idp.example.com/auth",
        token_endpoint="https://idp.example.com/token",
        jwks_uri="https://idp.example.com/keys",
        enabled=True,
        default_role="viewer",
    )
    service.scim_upsert_user(
        tenant_id="tenant-a",
        external_id="u1",
        email="u1@example.com",
        display_name="U1",
        active=True,
        role="operator",
    )

    authn = service.authenticate(
        tenant_id="tenant-a",
        provider_id="okta",
        subject="sub-1",
        email="u1@example.com",
        groups=["ops"],
    )
    assert authn["authenticated"] is True

    reloaded = EnterpriseIdentityFederationService(store=JsonFileIdentityFederationStore(str(store_path)))
    providers = reloaded.list_providers(tenant_id="tenant-a")
    users = reloaded.list_scim_users(tenant_id="tenant-a")

    assert len(providers) == 1
    assert len(users) == 1
