"""Tenant-scoped data residency policy service."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class DataResidencyStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryDataResidencyStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {tenant_id: dict(item) for tenant_id, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {tenant_id: dict(item) for tenant_id, item in self._payload.items()}


class JsonFileDataResidencyStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for tenant_id, payload in loaded.items():
            if isinstance(tenant_id, str) and isinstance(payload, dict):
                result[tenant_id] = dict(payload)
        return result


class TenantDataResidencyPolicyService:
    def __init__(self, *, store: DataResidencyStore | None = None) -> None:
        self._store = store or InMemoryDataResidencyStore()
        self._policies = self._store.load()

    def set_policy(
        self,
        *,
        tenant_id: str,
        allowed_regions: list[str],
        default_region: str | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_regions = sorted({item.strip().lower() for item in allowed_regions if item.strip()})
        if not normalized_regions:
            raise ValueError("allowed_regions must contain at least one region")

        resolved_default = (default_region or "").strip().lower()
        if not resolved_default:
            resolved_default = normalized_regions[0]
        if resolved_default not in normalized_regions:
            raise ValueError("default_region must be one of allowed_regions")

        now = time.time()
        existing = self._policies.get(normalized_tenant)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "tenant_id": normalized_tenant,
            "allowed_regions": normalized_regions,
            "default_region": resolved_default,
            "created_at": created_at,
            "updated_at": now,
        }
        self._policies[normalized_tenant] = payload
        self._persist()
        return dict(payload)

    def get_policy(self, *, tenant_id: str) -> dict[str, Any]:
        payload = self._policies.get(tenant_id)
        if payload is None:
            raise KeyError(tenant_id)
        return dict(payload)

    def list_policies(self) -> list[dict[str, Any]]:
        return [dict(self._policies[key]) for key in sorted(self._policies.keys())]

    def validate(self, *, tenant_id: str, region: str | None) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        policy = self._policies.get(normalized_tenant)
        normalized_region = (region or "").strip().lower()
        if policy is None:
            return {
                "tenant_id": normalized_tenant,
                "region": normalized_region,
                "allowed": True,
                "reason": "no_residency_policy",
            }

        allowed_regions = [str(item) for item in policy.get("allowed_regions", [])]
        if not normalized_region:
            normalized_region = str(policy.get("default_region", ""))

        allowed = normalized_region in allowed_regions
        reason = "region_allowed" if allowed else "region_not_permitted"
        return {
            "tenant_id": normalized_tenant,
            "region": normalized_region,
            "allowed": allowed,
            "reason": reason,
            "allowed_regions": allowed_regions,
            "default_region": str(policy.get("default_region", "")),
        }

    def _persist(self) -> None:
        self._store.save(self._policies)
