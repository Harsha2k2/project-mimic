"""Enterprise identity federation with OIDC/SAML auth config and SCIM provisioning."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class IdentityFederationStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryIdentityFederationStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileIdentityFederationStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}
        return dict(loaded)


class EnterpriseIdentityFederationService:
    def __init__(self, *, store: IdentityFederationStore | None = None) -> None:
        self._store = store or InMemoryIdentityFederationStore()
        loaded = self._store.load()
        self._providers: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("providers", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._scim_users: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("scim_users", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._scim_groups: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("scim_groups", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_provider(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        protocol: str,
        issuer: str,
        client_id: str,
        metadata_url: str | None = None,
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        jwks_uri: str | None = None,
        saml_sso_url: str | None = None,
        saml_entity_id: str | None = None,
        enabled: bool = True,
        default_role: str = "viewer",
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_provider_id = provider_id.strip().lower()
        if not normalized_provider_id:
            raise ValueError("provider_id must not be empty")

        normalized_protocol = protocol.strip().lower()
        if normalized_protocol not in {"oidc", "saml"}:
            raise ValueError("protocol must be oidc or saml")

        normalized_issuer = issuer.strip()
        if not normalized_issuer:
            raise ValueError("issuer must not be empty")

        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise ValueError("client_id must not be empty")

        normalized_default_role = default_role.strip().lower()
        if normalized_default_role not in {"viewer", "operator", "admin"}:
            raise ValueError("default_role must be viewer|operator|admin")

        if normalized_protocol == "oidc":
            if not (authorization_endpoint and authorization_endpoint.strip()):
                raise ValueError("authorization_endpoint is required for oidc")
            if not (token_endpoint and token_endpoint.strip()):
                raise ValueError("token_endpoint is required for oidc")

        if normalized_protocol == "saml":
            if not (saml_sso_url and saml_sso_url.strip()):
                raise ValueError("saml_sso_url is required for saml")
            if not (saml_entity_id and saml_entity_id.strip()):
                raise ValueError("saml_entity_id is required for saml")

        now = time.time()
        existing = self._providers.get(normalized_provider_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "tenant_id": normalized_tenant,
            "provider_id": normalized_provider_id,
            "protocol": normalized_protocol,
            "issuer": normalized_issuer,
            "client_id": normalized_client_id,
            "metadata_url": metadata_url.strip() if metadata_url and metadata_url.strip() else None,
            "authorization_endpoint": (
                authorization_endpoint.strip()
                if authorization_endpoint and authorization_endpoint.strip()
                else None
            ),
            "token_endpoint": token_endpoint.strip() if token_endpoint and token_endpoint.strip() else None,
            "jwks_uri": jwks_uri.strip() if jwks_uri and jwks_uri.strip() else None,
            "saml_sso_url": saml_sso_url.strip() if saml_sso_url and saml_sso_url.strip() else None,
            "saml_entity_id": saml_entity_id.strip() if saml_entity_id and saml_entity_id.strip() else None,
            "enabled": bool(enabled),
            "default_role": normalized_default_role,
            "created_at": created_at,
            "updated_at": now,
        }
        self._providers[normalized_provider_id] = payload
        self._persist()
        return dict(payload)

    def get_provider(self, *, provider_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_provider_id = provider_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_provider_id:
            raise ValueError("provider_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._providers.get(normalized_provider_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def list_providers(self, *, tenant_id: str) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        items = [
            dict(item)
            for item in self._providers.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        items.sort(key=lambda item: str(item.get("provider_id", "")))
        return items

    def scim_upsert_user(
        self,
        *,
        tenant_id: str,
        external_id: str,
        email: str,
        display_name: str,
        active: bool,
        role: str,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_external_id = external_id.strip().lower()
        if not normalized_external_id:
            raise ValueError("external_id must not be empty")

        normalized_email = email.strip().lower()
        if "@" not in normalized_email:
            raise ValueError("email must be valid")

        normalized_display_name = display_name.strip()
        if not normalized_display_name:
            raise ValueError("display_name must not be empty")

        normalized_role = role.strip().lower()
        if normalized_role not in {"viewer", "operator", "admin"}:
            raise ValueError("role must be viewer|operator|admin")

        key = f"{normalized_tenant}::{normalized_external_id}"
        now = time.time()
        existing = self._scim_users.get(key)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "user_id": str(existing.get("user_id")) if existing is not None else f"scim_usr_{uuid4().hex[:12]}",
            "tenant_id": normalized_tenant,
            "external_id": normalized_external_id,
            "email": normalized_email,
            "display_name": normalized_display_name,
            "active": bool(active),
            "role": normalized_role,
            "created_at": created_at,
            "updated_at": now,
        }
        self._scim_users[key] = payload
        self._persist()
        return dict(payload)

    def list_scim_users(self, *, tenant_id: str, active: bool | None = None) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        items: list[dict[str, Any]] = []
        for payload in self._scim_users.values():
            if str(payload.get("tenant_id", "")) != normalized_tenant:
                continue
            if active is not None and bool(payload.get("active", False)) != bool(active):
                continue
            items.append(dict(payload))

        items.sort(key=lambda item: str(item.get("external_id", "")))
        return items

    def scim_upsert_group(
        self,
        *,
        tenant_id: str,
        external_id: str,
        display_name: str,
        members: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_external_id = external_id.strip().lower()
        if not normalized_external_id:
            raise ValueError("external_id must not be empty")

        normalized_display_name = display_name.strip()
        if not normalized_display_name:
            raise ValueError("display_name must not be empty")

        normalized_members = sorted(
            {
                item.strip().lower()
                for item in (members or [])
                if item.strip()
            }
        )

        key = f"{normalized_tenant}::{normalized_external_id}"
        now = time.time()
        existing = self._scim_groups.get(key)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "group_id": str(existing.get("group_id")) if existing is not None else f"scim_grp_{uuid4().hex[:12]}",
            "tenant_id": normalized_tenant,
            "external_id": normalized_external_id,
            "display_name": normalized_display_name,
            "members": normalized_members,
            "created_at": created_at,
            "updated_at": now,
        }
        self._scim_groups[key] = payload
        self._persist()
        return dict(payload)

    def list_scim_groups(self, *, tenant_id: str) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        items = [
            dict(item)
            for item in self._scim_groups.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        items.sort(key=lambda item: str(item.get("external_id", "")))
        return items

    def authenticate(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        subject: str,
        email: str,
        groups: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        normalized_provider_id = provider_id.strip().lower()
        normalized_subject = subject.strip()
        normalized_email = email.strip().lower()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_provider_id:
            raise ValueError("provider_id must not be empty")
        if not normalized_subject:
            raise ValueError("subject must not be empty")
        if "@" not in normalized_email:
            raise ValueError("email must be valid")

        provider = self.get_provider(provider_id=normalized_provider_id, tenant_id=normalized_tenant)
        if provider is None:
            raise ValueError("provider not found")
        if not bool(provider.get("enabled", False)):
            raise ValueError("provider is disabled")

        mapped_user = None
        for payload in self.list_scim_users(tenant_id=normalized_tenant):
            if str(payload.get("email", "")).lower() == normalized_email:
                mapped_user = payload
                break

        effective_role = str(provider.get("default_role", "viewer"))
        if mapped_user is not None and bool(mapped_user.get("active", False)):
            effective_role = str(mapped_user.get("role", effective_role))

        normalized_groups = sorted({item.strip().lower() for item in (groups or []) if item.strip()})
        return {
            "tenant_id": normalized_tenant,
            "provider_id": normalized_provider_id,
            "subject": normalized_subject,
            "email": normalized_email,
            "groups": normalized_groups,
            "role": effective_role,
            "scim_user_id": (None if mapped_user is None else mapped_user.get("user_id")),
            "authenticated": True,
            "authenticated_at": time.time(),
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "providers": self._providers,
                "scim_users": self._scim_users,
                "scim_groups": self._scim_groups,
            }
        )
