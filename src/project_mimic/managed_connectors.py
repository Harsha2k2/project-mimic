"""Partner integration templates and managed connector orchestration."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class ManagedConnectorStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryManagedConnectorStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileManagedConnectorStore:
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


class PartnerIntegrationService:
    def __init__(self, *, store: ManagedConnectorStore | None = None) -> None:
        self._store = store or InMemoryManagedConnectorStore()
        loaded = self._store.load()
        self._templates: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("templates", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._connectors: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("connectors", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_template(
        self,
        *,
        template_id: str,
        provider: str,
        category: str,
        auth_type: str,
        required_config_keys: list[str],
        optional_config_keys: list[str] | None = None,
        default_scopes: list[str] | None = None,
        webhook_supported: bool = True,
        rate_limit_per_minute: int = 120,
    ) -> dict[str, Any]:
        normalized_template_id = template_id.strip().lower()
        if not normalized_template_id:
            raise ValueError("template_id must not be empty")

        normalized_provider = provider.strip().lower()
        if not normalized_provider:
            raise ValueError("provider must not be empty")

        normalized_category = category.strip().lower()
        if not normalized_category:
            raise ValueError("category must not be empty")

        normalized_auth_type = auth_type.strip().lower()
        if normalized_auth_type not in {"api_key", "oauth2", "service_account", "basic"}:
            raise ValueError("auth_type must be api_key|oauth2|service_account|basic")

        normalized_required = sorted({item.strip().lower() for item in required_config_keys if item.strip()})
        if not normalized_required:
            raise ValueError("required_config_keys must not be empty")

        normalized_optional = sorted(
            {item.strip().lower() for item in (optional_config_keys or []) if item.strip()}
        )
        normalized_scopes = sorted({item.strip() for item in (default_scopes or []) if item.strip()})

        validated_rate_limit = int(rate_limit_per_minute)
        if validated_rate_limit <= 0:
            raise ValueError("rate_limit_per_minute must be > 0")

        now = time.time()
        existing = self._templates.get(normalized_template_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "template_id": normalized_template_id,
            "provider": normalized_provider,
            "category": normalized_category,
            "auth_type": normalized_auth_type,
            "required_config_keys": normalized_required,
            "optional_config_keys": normalized_optional,
            "default_scopes": normalized_scopes,
            "webhook_supported": bool(webhook_supported),
            "rate_limit_per_minute": validated_rate_limit,
            "created_at": created_at,
            "updated_at": now,
        }
        self._templates[normalized_template_id] = payload
        self._persist()
        return dict(payload)

    def list_templates(self, *, category: str | None = None) -> list[dict[str, Any]]:
        normalized_category = category.strip().lower() if category is not None else ""
        items = [dict(item) for item in self._templates.values()]
        if normalized_category:
            items = [item for item in items if str(item.get("category", "")) == normalized_category]
        items.sort(key=lambda item: str(item.get("template_id", "")))
        return items

    def get_template(self, *, template_id: str) -> dict[str, Any] | None:
        normalized_template_id = template_id.strip().lower()
        if not normalized_template_id:
            raise ValueError("template_id must not be empty")
        payload = self._templates.get(normalized_template_id)
        if payload is None:
            return None
        return dict(payload)

    def create_connector(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        template_id: str,
        name: str,
        config: dict[str, str],
        enabled: bool = True,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_connector_id = connector_id.strip().lower()
        if not normalized_connector_id:
            raise ValueError("connector_id must not be empty")

        if normalized_connector_id in self._connectors:
            raise ValueError("connector already exists")

        normalized_template_id = template_id.strip().lower()
        template = self._templates.get(normalized_template_id)
        if template is None:
            raise ValueError("template not found")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name must not be empty")

        normalized_config = {
            str(key).strip().lower(): str(value).strip()
            for key, value in dict(config).items()
            if str(key).strip()
        }

        required_keys = [str(item) for item in template.get("required_config_keys", []) if isinstance(item, str)]
        missing_keys = [key for key in required_keys if key not in normalized_config or not normalized_config[key]]
        if missing_keys:
            raise ValueError(f"missing required connector config keys: {', '.join(sorted(missing_keys))}")

        now = time.time()
        payload = {
            "connector_id": normalized_connector_id,
            "tenant_id": normalized_tenant,
            "template_id": normalized_template_id,
            "name": normalized_name,
            "config": normalized_config,
            "enabled": bool(enabled),
            "health": "unknown",
            "last_checked_at": None,
            "last_error": None,
            "created_at": now,
            "updated_at": now,
        }
        self._connectors[normalized_connector_id] = payload
        self._persist()
        return dict(payload)

    def update_connector(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        name: str | None = None,
        config: dict[str, str] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        normalized_connector_id = connector_id.strip().lower()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_connector_id:
            raise ValueError("connector_id must not be empty")

        existing = self._connectors.get(normalized_connector_id)
        if existing is None:
            raise ValueError("connector not found")
        if str(existing.get("tenant_id", "")) != normalized_tenant:
            raise ValueError("connector does not belong to tenant")

        updated = dict(existing)
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("name must not be empty")
            updated["name"] = normalized_name

        if config is not None:
            normalized_config = {
                str(key).strip().lower(): str(value).strip()
                for key, value in dict(config).items()
                if str(key).strip()
            }
            template_id = str(updated.get("template_id", ""))
            template = self._templates.get(template_id)
            if template is None:
                raise ValueError("template not found")
            required_keys = [str(item) for item in template.get("required_config_keys", []) if isinstance(item, str)]
            missing_keys = [key for key in required_keys if key not in normalized_config or not normalized_config[key]]
            if missing_keys:
                raise ValueError(f"missing required connector config keys: {', '.join(sorted(missing_keys))}")
            updated["config"] = normalized_config

        if enabled is not None:
            updated["enabled"] = bool(enabled)

        updated["updated_at"] = time.time()
        self._connectors[normalized_connector_id] = updated
        self._persist()
        return dict(updated)

    def get_connector(self, *, tenant_id: str, connector_id: str) -> dict[str, Any] | None:
        normalized_tenant = tenant_id.strip()
        normalized_connector_id = connector_id.strip().lower()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_connector_id:
            raise ValueError("connector_id must not be empty")

        payload = self._connectors.get(normalized_connector_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def list_connectors(self, *, tenant_id: str, enabled: bool | None = None) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        items: list[dict[str, Any]] = []
        for payload in self._connectors.values():
            if str(payload.get("tenant_id", "")) != normalized_tenant:
                continue
            if enabled is not None and bool(payload.get("enabled", False)) != bool(enabled):
                continue
            items.append(dict(payload))

        items.sort(key=lambda item: str(item.get("connector_id", "")))
        return items

    def check_connector_health(self, *, tenant_id: str, connector_id: str) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        normalized_connector_id = connector_id.strip().lower()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_connector_id:
            raise ValueError("connector_id must not be empty")

        existing = self._connectors.get(normalized_connector_id)
        if existing is None:
            raise ValueError("connector not found")
        if str(existing.get("tenant_id", "")) != normalized_tenant:
            raise ValueError("connector does not belong to tenant")

        updated = dict(existing)
        is_enabled = bool(updated.get("enabled", False))
        has_minimum_config = bool(dict(updated.get("config", {})))
        healthy = is_enabled and has_minimum_config

        updated["health"] = "healthy" if healthy else "unhealthy"
        updated["last_checked_at"] = time.time()
        updated["last_error"] = None if healthy else "connector disabled or missing configuration"
        updated["updated_at"] = float(updated.get("last_checked_at", time.time()))
        self._connectors[normalized_connector_id] = updated
        self._persist()

        return {
            "connector_id": normalized_connector_id,
            "tenant_id": normalized_tenant,
            "health": str(updated.get("health", "unknown")),
            "healthy": healthy,
            "last_checked_at": float(updated.get("last_checked_at", 0.0)),
            "last_error": updated.get("last_error"),
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "templates": self._templates,
                "connectors": self._connectors,
            }
        )
