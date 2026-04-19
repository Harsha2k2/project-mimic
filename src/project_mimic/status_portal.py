"""Customer-facing SLA and status portal support service."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class StatusPortalStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryStatusPortalStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileStatusPortalStore:
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


class CustomerStatusPortalService:
    def __init__(self, *, store: StatusPortalStore | None = None) -> None:
        self._store = store or InMemoryStatusPortalStore()
        loaded = self._store.load()
        self._service_statuses: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("service_statuses", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._sla_targets: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("sla_targets", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_service_status(
        self,
        *,
        service_id: str,
        display_name: str,
        status: str,
        availability_percent: float,
        latency_p95_ms: float,
        error_rate_percent: float,
        components: dict[str, str] | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        normalized_service_id = service_id.strip().lower()
        if not normalized_service_id:
            raise ValueError("service_id must not be empty")

        normalized_display_name = display_name.strip()
        if not normalized_display_name:
            raise ValueError("display_name must not be empty")

        normalized_status = status.strip().lower()
        allowed_statuses = {"operational", "degraded", "partial_outage", "major_outage", "maintenance"}
        if normalized_status not in allowed_statuses:
            raise ValueError("status must be one of operational|degraded|partial_outage|major_outage|maintenance")

        validated_availability = float(availability_percent)
        if validated_availability < 0.0 or validated_availability > 100.0:
            raise ValueError("availability_percent must be within [0, 100]")

        validated_latency = float(latency_p95_ms)
        if validated_latency < 0.0:
            raise ValueError("latency_p95_ms must be >= 0")

        validated_error_rate = float(error_rate_percent)
        if validated_error_rate < 0.0 or validated_error_rate > 100.0:
            raise ValueError("error_rate_percent must be within [0, 100]")

        normalized_components = {
            str(key).strip().lower(): str(value).strip().lower()
            for key, value in dict(components or {}).items()
            if str(key).strip() and str(value).strip()
        }

        now = time.time()
        existing = self._service_statuses.get(normalized_service_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "service_id": normalized_service_id,
            "display_name": normalized_display_name,
            "status": normalized_status,
            "availability_percent": validated_availability,
            "latency_p95_ms": validated_latency,
            "error_rate_percent": validated_error_rate,
            "components": normalized_components,
            "message": message.strip() if message is not None and message.strip() else None,
            "created_at": created_at,
            "updated_at": now,
        }
        self._service_statuses[normalized_service_id] = payload
        self._persist()
        return dict(payload)

    def list_service_statuses(self) -> list[dict[str, Any]]:
        items = [dict(item) for item in self._service_statuses.values()]
        items.sort(key=lambda item: str(item.get("service_id", "")))
        return items

    def get_service_status(self, *, service_id: str) -> dict[str, Any] | None:
        normalized_service_id = service_id.strip().lower()
        if not normalized_service_id:
            raise ValueError("service_id must not be empty")
        payload = self._service_statuses.get(normalized_service_id)
        if payload is None:
            return None
        return dict(payload)

    def upsert_sla_target(
        self,
        *,
        service_id: str,
        availability_target_percent: float,
        latency_p95_target_ms: float,
        error_rate_target_percent: float,
        window_days: int,
    ) -> dict[str, Any]:
        normalized_service_id = service_id.strip().lower()
        if not normalized_service_id:
            raise ValueError("service_id must not be empty")

        availability_target = float(availability_target_percent)
        if availability_target < 0.0 or availability_target > 100.0:
            raise ValueError("availability_target_percent must be within [0, 100]")

        latency_target = float(latency_p95_target_ms)
        if latency_target <= 0.0:
            raise ValueError("latency_p95_target_ms must be > 0")

        error_target = float(error_rate_target_percent)
        if error_target < 0.0 or error_target > 100.0:
            raise ValueError("error_rate_target_percent must be within [0, 100]")

        validated_window_days = int(window_days)
        if validated_window_days <= 0:
            raise ValueError("window_days must be > 0")

        now = time.time()
        existing = self._sla_targets.get(normalized_service_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "service_id": normalized_service_id,
            "availability_target_percent": availability_target,
            "latency_p95_target_ms": latency_target,
            "error_rate_target_percent": error_target,
            "window_days": validated_window_days,
            "created_at": created_at,
            "updated_at": now,
        }
        self._sla_targets[normalized_service_id] = payload
        self._persist()
        return dict(payload)

    def list_sla_targets(self) -> list[dict[str, Any]]:
        items = [dict(item) for item in self._sla_targets.values()]
        items.sort(key=lambda item: str(item.get("service_id", "")))
        return items

    def get_sla_target(self, *, service_id: str) -> dict[str, Any] | None:
        normalized_service_id = service_id.strip().lower()
        if not normalized_service_id:
            raise ValueError("service_id must not be empty")
        payload = self._sla_targets.get(normalized_service_id)
        if payload is None:
            return None
        return dict(payload)

    def evaluate_sla(self, *, service_id: str) -> dict[str, Any]:
        status = self.get_service_status(service_id=service_id)
        if status is None:
            raise ValueError("service status not found")

        target = self.get_sla_target(service_id=service_id)
        if target is None:
            raise ValueError("sla target not found")

        availability_ok = float(status.get("availability_percent", 0.0)) >= float(
            target.get("availability_target_percent", 0.0)
        )
        latency_ok = float(status.get("latency_p95_ms", 0.0)) <= float(target.get("latency_p95_target_ms", 0.0))
        error_rate_ok = float(status.get("error_rate_percent", 100.0)) <= float(
            target.get("error_rate_target_percent", 0.0)
        )

        violations: list[str] = []
        if not availability_ok:
            violations.append("availability")
        if not latency_ok:
            violations.append("latency_p95")
        if not error_rate_ok:
            violations.append("error_rate")

        return {
            "service_id": str(status.get("service_id", "")),
            "meets_sla": len(violations) == 0,
            "availability_ok": availability_ok,
            "latency_ok": latency_ok,
            "error_rate_ok": error_rate_ok,
            "violations": violations,
            "status": status,
            "target": target,
            "evaluated_at": time.time(),
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "service_statuses": self._service_statuses,
                "sla_targets": self._sla_targets,
            }
        )
