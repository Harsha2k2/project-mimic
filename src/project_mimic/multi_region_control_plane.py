"""Multi-region active-active control plane topology and routing service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any, Protocol


class MultiRegionControlPlaneStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryMultiRegionControlPlaneStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {region_id: dict(item) for region_id, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {region_id: dict(item) for region_id, item in self._payload.items()}


class JsonFileMultiRegionControlPlaneStore:
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
        for region_id, payload in loaded.items():
            if isinstance(region_id, str) and isinstance(payload, dict):
                result[region_id] = dict(payload)
        return result


class MultiRegionControlPlaneService:
    def __init__(self, *, store: MultiRegionControlPlaneStore | None = None) -> None:
        self._store = store or InMemoryMultiRegionControlPlaneStore()
        self._regions = self._store.load()

    def upsert_region(
        self,
        *,
        region_id: str,
        endpoint: str,
        traffic_weight: float = 1.0,
        write_enabled: bool = True,
        read_enabled: bool = True,
        priority: int = 100,
    ) -> dict[str, Any]:
        normalized_region = region_id.strip().lower()
        if not normalized_region:
            raise ValueError("region_id must not be empty")

        normalized_endpoint = endpoint.strip()
        if not normalized_endpoint:
            raise ValueError("endpoint must not be empty")

        normalized_weight = float(traffic_weight)
        if normalized_weight <= 0:
            raise ValueError("traffic_weight must be greater than zero")

        normalized_priority = int(priority)
        if normalized_priority < 0:
            raise ValueError("priority must be non-negative")

        now = time.time()
        existing = self._regions.get(normalized_region)
        created_at = now if existing is None else float(existing.get("created_at", now))
        last_heartbeat = now if existing is None else float(existing.get("last_heartbeat_at", now))
        health_reason = ""
        if existing is not None:
            health_reason = str(existing.get("health_reason", ""))

        payload = {
            "region_id": normalized_region,
            "endpoint": normalized_endpoint,
            "traffic_weight": normalized_weight,
            "write_enabled": bool(write_enabled),
            "read_enabled": bool(read_enabled),
            "priority": normalized_priority,
            "healthy": True if existing is None else bool(existing.get("healthy", True)),
            "health_reason": health_reason,
            "last_heartbeat_at": last_heartbeat,
            "created_at": created_at,
            "updated_at": now,
        }
        self._regions[normalized_region] = payload
        self._persist()
        return dict(payload)

    def get_region(self, *, region_id: str) -> dict[str, Any]:
        normalized_region = region_id.strip().lower()
        payload = self._regions.get(normalized_region)
        if payload is None:
            raise KeyError(normalized_region)
        return dict(payload)

    def list_regions(self) -> list[dict[str, Any]]:
        return [dict(self._regions[key]) for key in sorted(self._regions.keys())]

    def update_health(
        self,
        *,
        region_id: str,
        healthy: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload = self.get_region(region_id=region_id)
        now = time.time()
        payload["healthy"] = bool(healthy)
        payload["health_reason"] = (reason or "").strip()
        payload["last_heartbeat_at"] = now
        payload["updated_at"] = now
        self._regions[str(payload["region_id"])] = payload
        self._persist()
        return dict(payload)

    def route(
        self,
        *,
        tenant_id: str,
        operation: str,
        preferred_region: str | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_operation = operation.strip().lower()
        if normalized_operation not in {"read", "write"}:
            raise ValueError("operation must be either 'read' or 'write'")

        candidates = self._eligible_regions(operation=normalized_operation)
        selected_reason = "weighted_active_active_routing"

        normalized_preferred = (preferred_region or "").strip().lower()
        if normalized_preferred:
            preferred_candidate = next(
                (item for item in candidates if str(item.get("region_id", "")) == normalized_preferred),
                None,
            )
            if preferred_candidate is not None:
                selected_reason = "preferred_region_selected"
                return self._route_payload(
                    tenant_id=normalized_tenant,
                    operation=normalized_operation,
                    selected=preferred_candidate,
                    reason=selected_reason,
                )
            selected_reason = "preferred_region_unavailable_fallback"

        selected = self._weighted_pick(candidates, route_key=f"{normalized_tenant}:{normalized_operation}")
        return self._route_payload(
            tenant_id=normalized_tenant,
            operation=normalized_operation,
            selected=selected,
            reason=selected_reason,
        )

    def topology_snapshot(self) -> dict[str, Any]:
        regions = self.list_regions()
        healthy_regions = [str(item["region_id"]) for item in regions if bool(item.get("healthy", False))]
        writable_regions = [
            str(item["region_id"])
            for item in regions
            if bool(item.get("healthy", False)) and bool(item.get("write_enabled", False))
        ]
        readable_regions = [
            str(item["region_id"])
            for item in regions
            if bool(item.get("healthy", False)) and bool(item.get("read_enabled", False))
        ]
        updated_at = max((float(item.get("updated_at", 0.0)) for item in regions), default=0.0)
        return {
            "mode": "active-active",
            "total_regions": len(regions),
            "healthy_regions": healthy_regions,
            "writable_regions": writable_regions,
            "readable_regions": readable_regions,
            "active_active_ready": len(writable_regions) >= 2 and len(readable_regions) >= 2,
            "primary_region": self._select_primary_region(regions),
            "updated_at": updated_at,
        }

    def _eligible_regions(self, *, operation: str) -> list[dict[str, Any]]:
        if operation == "read":
            eligible = [
                item
                for item in self.list_regions()
                if bool(item.get("healthy", False)) and bool(item.get("read_enabled", False))
            ]
        else:
            eligible = [
                item
                for item in self.list_regions()
                if bool(item.get("healthy", False)) and bool(item.get("write_enabled", False))
            ]

        if not eligible:
            raise ValueError("no healthy regions available for operation")
        return eligible

    def _weighted_pick(self, candidates: list[dict[str, Any]], *, route_key: str) -> dict[str, Any]:
        sorted_candidates = sorted(candidates, key=lambda item: str(item.get("region_id", "")))
        total_weight = sum(max(float(item.get("traffic_weight", 0.0)), 0.0) for item in sorted_candidates)
        if total_weight <= 0:
            return sorted_candidates[0]

        digest = hashlib.sha256(route_key.encode("utf-8")).hexdigest()
        ticket = int(digest[:12], 16) / float(16**12)

        threshold = 0.0
        for candidate in sorted_candidates:
            weight = max(float(candidate.get("traffic_weight", 0.0)), 0.0)
            threshold += weight / total_weight
            if ticket <= threshold:
                return candidate

        return sorted_candidates[-1]

    def _select_primary_region(self, regions: list[dict[str, Any]]) -> str | None:
        healthy_writable = [
            item
            for item in regions
            if bool(item.get("healthy", False)) and bool(item.get("write_enabled", False))
        ]
        if not healthy_writable:
            return None

        winner = min(
            healthy_writable,
            key=lambda item: (int(item.get("priority", 100)), str(item.get("region_id", ""))),
        )
        return str(winner.get("region_id", ""))

    def _route_payload(
        self,
        *,
        tenant_id: str,
        operation: str,
        selected: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "operation": operation,
            "selected_region": str(selected.get("region_id", "")),
            "endpoint": str(selected.get("endpoint", "")),
            "reason": reason,
            "routed_at": time.time(),
        }

    def _persist(self) -> None:
        self._store.save(self._regions)
