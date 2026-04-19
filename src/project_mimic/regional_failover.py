"""Regional failover orchestration with traffic control policies."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol

from .multi_region_control_plane import MultiRegionControlPlaneService


class RegionalFailoverStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryRegionalFailoverStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileRegionalFailoverStore:
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


class RegionalFailoverOrchestrator:
    def __init__(
        self,
        *,
        control_plane: MultiRegionControlPlaneService,
        store: RegionalFailoverStore | None = None,
    ) -> None:
        self._control_plane = control_plane
        self._store = store or InMemoryRegionalFailoverStore()
        payload = self._store.load()
        self._policies: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("policies", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._active_failovers: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("active_failovers", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._history: list[dict[str, Any]] = [
            dict(item) for item in payload.get("history", []) if isinstance(item, dict)
        ]

    def upsert_policy(
        self,
        *,
        policy_id: str,
        primary_region: str,
        secondary_region: str,
        read_traffic_percent: dict[str, float],
        write_region: str | None = None,
        auto_failback: bool = False,
    ) -> dict[str, Any]:
        normalized_policy_id = policy_id.strip().lower()
        if not normalized_policy_id:
            raise ValueError("policy_id must not be empty")

        normalized_primary = primary_region.strip().lower()
        normalized_secondary = secondary_region.strip().lower()
        if not normalized_primary:
            raise ValueError("primary_region must not be empty")
        if not normalized_secondary:
            raise ValueError("secondary_region must not be empty")

        normalized_read_distribution = self._normalize_read_distribution(read_traffic_percent)
        if normalized_primary not in normalized_read_distribution:
            raise ValueError("primary_region must exist in read_traffic_percent")
        if normalized_secondary not in normalized_read_distribution:
            raise ValueError("secondary_region must exist in read_traffic_percent")

        resolved_write_region = (write_region or normalized_primary).strip().lower()
        if resolved_write_region not in normalized_read_distribution:
            raise ValueError("write_region must exist in read_traffic_percent")

        for region_id in normalized_read_distribution:
            self._ensure_region_exists(region_id)

        now = time.time()
        existing = self._policies.get(normalized_policy_id)
        created_at = now if existing is None else float(existing.get("created_at", now))
        last_applied_at = None if existing is None else existing.get("last_applied_at")

        payload = {
            "policy_id": normalized_policy_id,
            "primary_region": normalized_primary,
            "secondary_region": normalized_secondary,
            "read_traffic_percent": normalized_read_distribution,
            "write_region": resolved_write_region,
            "auto_failback": bool(auto_failback),
            "last_applied_at": last_applied_at,
            "created_at": created_at,
            "updated_at": now,
        }
        self._policies[normalized_policy_id] = payload
        self._persist()
        return dict(payload)

    def get_policy(self, *, policy_id: str) -> dict[str, Any]:
        normalized_policy_id = policy_id.strip().lower()
        payload = self._policies.get(normalized_policy_id)
        if payload is None:
            raise KeyError(normalized_policy_id)
        return dict(payload)

    def list_policies(self) -> list[dict[str, Any]]:
        return [dict(self._policies[key]) for key in sorted(self._policies.keys())]

    def apply_policy(self, *, policy_id: str, initiated_by: str) -> dict[str, Any]:
        policy = self.get_policy(policy_id=policy_id)
        distribution = dict(policy.get("read_traffic_percent", {}))
        write_region = str(policy.get("write_region", ""))

        applied_regions: list[dict[str, Any]] = []
        for region_id in sorted(distribution.keys()):
            percent = float(distribution.get(region_id, 0.0))
            existing = self._control_plane.get_region(region_id=region_id)
            read_enabled = percent > 0.0
            updated = self._control_plane.upsert_region(
                region_id=region_id,
                endpoint=str(existing.get("endpoint", "")),
                traffic_weight=(percent if read_enabled else 0.0001),
                write_enabled=(region_id == write_region),
                read_enabled=read_enabled,
                priority=int(existing.get("priority", 100)),
            )
            applied_regions.append(
                {
                    "region_id": str(updated.get("region_id", region_id)),
                    "read_percent": percent,
                    "read_enabled": bool(updated.get("read_enabled", read_enabled)),
                    "write_enabled": bool(updated.get("write_enabled", region_id == write_region)),
                }
            )

        applied_at = time.time()
        policy["last_applied_at"] = applied_at
        policy["updated_at"] = applied_at
        self._policies[str(policy["policy_id"])] = policy

        event = {
            "event_type": "policy_applied",
            "policy_id": str(policy["policy_id"]),
            "initiated_by": initiated_by,
            "applied_at": applied_at,
            "write_region": write_region,
            "applied_regions": applied_regions,
        }
        self._history.append(event)
        self._persist()
        return dict(event)

    def execute_failover(
        self,
        *,
        policy_id: str,
        target_region: str,
        reason: str,
        initiated_by: str,
    ) -> dict[str, Any]:
        policy = self.get_policy(policy_id=policy_id)
        normalized_policy_id = str(policy["policy_id"])
        if normalized_policy_id in self._active_failovers:
            raise ValueError("a failover is already active for this policy")

        normalized_target = target_region.strip().lower()
        if not normalized_target:
            raise ValueError("target_region must not be empty")

        regions = sorted({str(key) for key in dict(policy.get("read_traffic_percent", {})).keys()})
        if normalized_target not in regions:
            raise ValueError("target_region must exist in the failover policy read distribution")

        previous_snapshot: dict[str, dict[str, Any]] = {}
        for region_id in regions:
            existing = self._control_plane.get_region(region_id=region_id)
            previous_snapshot[region_id] = {
                "region_id": str(existing.get("region_id", region_id)),
                "endpoint": str(existing.get("endpoint", "")),
                "traffic_weight": float(existing.get("traffic_weight", 1.0)),
                "write_enabled": bool(existing.get("write_enabled", True)),
                "read_enabled": bool(existing.get("read_enabled", True)),
                "priority": int(existing.get("priority", 100)),
            }

        for region_id in regions:
            existing = previous_snapshot[region_id]
            is_target = region_id == normalized_target
            self._control_plane.upsert_region(
                region_id=region_id,
                endpoint=str(existing["endpoint"]),
                traffic_weight=(100.0 if is_target else 0.0001),
                write_enabled=is_target,
                read_enabled=is_target,
                priority=int(existing["priority"]),
            )

        now = time.time()
        active = {
            "policy_id": normalized_policy_id,
            "target_region": normalized_target,
            "reason": reason.strip() or "manual_failover",
            "initiated_by": initiated_by,
            "started_at": now,
            "updated_at": now,
            "previous_snapshot": previous_snapshot,
        }
        self._active_failovers[normalized_policy_id] = active
        self._history.append(
            {
                "event_type": "failover_executed",
                "policy_id": normalized_policy_id,
                "target_region": normalized_target,
                "reason": active["reason"],
                "initiated_by": initiated_by,
                "started_at": now,
            }
        )
        self._persist()
        return self.status(policy_id=normalized_policy_id)

    def recover_failover(
        self,
        *,
        policy_id: str,
        reason: str,
        recovered_by: str,
    ) -> dict[str, Any]:
        normalized_policy_id = policy_id.strip().lower()
        active = self._active_failovers.get(normalized_policy_id)
        if active is None:
            raise ValueError("no active failover found for policy")

        previous_snapshot = dict(active.get("previous_snapshot", {}))
        for region_id, snapshot in previous_snapshot.items():
            if not isinstance(snapshot, dict):
                continue
            self._control_plane.upsert_region(
                region_id=region_id,
                endpoint=str(snapshot.get("endpoint", "")),
                traffic_weight=float(snapshot.get("traffic_weight", 1.0)),
                write_enabled=bool(snapshot.get("write_enabled", True)),
                read_enabled=bool(snapshot.get("read_enabled", True)),
                priority=int(snapshot.get("priority", 100)),
            )

        now = time.time()
        resolved = {
            "event_type": "failover_recovered",
            "policy_id": normalized_policy_id,
            "target_region": active.get("target_region"),
            "reason": reason.strip() or "manual_recovery",
            "initiated_by": active.get("initiated_by"),
            "started_at": float(active.get("started_at", now)),
            "resolved_at": now,
            "recovered_by": recovered_by,
        }
        self._history.append(resolved)
        self._active_failovers.pop(normalized_policy_id, None)

        policy = self._policies.get(normalized_policy_id)
        if policy is not None and bool(policy.get("auto_failback", False)):
            self.apply_policy(policy_id=normalized_policy_id, initiated_by=recovered_by)

        self._persist()
        return self.status(policy_id=normalized_policy_id)

    def status(self, *, policy_id: str) -> dict[str, Any]:
        policy = self.get_policy(policy_id=policy_id)
        normalized_policy_id = str(policy["policy_id"])
        active = self._active_failovers.get(normalized_policy_id)
        if active is not None:
            return {
                "policy_id": normalized_policy_id,
                "active": True,
                "target_region": str(active.get("target_region", "")),
                "reason": str(active.get("reason", "manual_failover")),
                "initiated_by": str(active.get("initiated_by", "")) or None,
                "recovered_by": None,
                "started_at": float(active.get("started_at", 0.0)),
                "resolved_at": None,
                "updated_at": float(active.get("updated_at", 0.0)),
            }

        last_recovery = self._last_history_event(normalized_policy_id, event_type="failover_recovered")
        return {
            "policy_id": normalized_policy_id,
            "active": False,
            "target_region": (
                None
                if last_recovery is None or last_recovery.get("target_region") in {None, ""}
                else str(last_recovery.get("target_region"))
            ),
            "reason": (
                None
                if last_recovery is None or last_recovery.get("reason") in {None, ""}
                else str(last_recovery.get("reason"))
            ),
            "initiated_by": (
                None
                if last_recovery is None or last_recovery.get("initiated_by") in {None, ""}
                else str(last_recovery.get("initiated_by"))
            ),
            "recovered_by": (
                None
                if last_recovery is None or last_recovery.get("recovered_by") in {None, ""}
                else str(last_recovery.get("recovered_by"))
            ),
            "started_at": (
                None
                if last_recovery is None or last_recovery.get("started_at") is None
                else float(last_recovery.get("started_at"))
            ),
            "resolved_at": (
                None
                if last_recovery is None or last_recovery.get("resolved_at") is None
                else float(last_recovery.get("resolved_at"))
            ),
            "updated_at": (
                float(policy.get("updated_at", 0.0))
                if last_recovery is None
                else float(last_recovery.get("resolved_at", policy.get("updated_at", 0.0)))
            ),
        }

    def _last_history_event(self, policy_id: str, *, event_type: str) -> dict[str, Any] | None:
        for item in reversed(self._history):
            if str(item.get("policy_id", "")) != policy_id:
                continue
            if str(item.get("event_type", "")) != event_type:
                continue
            return dict(item)
        return None

    def _ensure_region_exists(self, region_id: str) -> None:
        try:
            self._control_plane.get_region(region_id=region_id)
        except KeyError as exc:
            raise ValueError(f"unknown control plane region: {region_id}") from exc

    def _normalize_read_distribution(self, payload: dict[str, float]) -> dict[str, float]:
        if not payload:
            raise ValueError("read_traffic_percent must include at least one region")

        normalized: dict[str, float] = {}
        for region_id, percent in payload.items():
            normalized_region = str(region_id).strip().lower()
            if not normalized_region:
                raise ValueError("read_traffic_percent keys must not be empty")
            numeric = float(percent)
            if numeric < 0:
                raise ValueError("read_traffic_percent values must be non-negative")
            normalized[normalized_region] = numeric

        total = sum(normalized.values())
        if total <= 0:
            raise ValueError("read_traffic_percent total must be greater than zero")

        return {
            region_id: round((value / total) * 100.0, 4)
            for region_id, value in sorted(normalized.items())
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "policies": self._policies,
                "active_failovers": self._active_failovers,
                "history": self._history,
            }
        )
