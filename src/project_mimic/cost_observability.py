"""Cost observability dashboard for GPU, queue, storage, and egress."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class CostObservabilityStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryCostObservabilityStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileCostObservabilityStore:
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


class CostObservabilityService:
    def __init__(self, *, store: CostObservabilityStore | None = None) -> None:
        self._store = store or InMemoryCostObservabilityStore()
        payload = self._store.load()
        self._snapshots: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("snapshots", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def record_snapshot(
        self,
        *,
        tenant_id: str,
        snapshot_id: str,
        period_start_day: int,
        period_end_day: int,
        gpu_hours: float,
        queue_compute_hours: float,
        storage_gb_month: float,
        egress_gb: float,
        rates: dict[str, float] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_snapshot_id = snapshot_id.strip().lower()
        if not normalized_snapshot_id:
            raise ValueError("snapshot_id must not be empty")

        validated_start_day = int(period_start_day)
        validated_end_day = int(period_end_day)
        if validated_end_day < validated_start_day:
            raise ValueError("period_end_day must be >= period_start_day")

        usage = {
            "gpu_hours": self._validate_non_negative(gpu_hours, "gpu_hours"),
            "queue_compute_hours": self._validate_non_negative(queue_compute_hours, "queue_compute_hours"),
            "storage_gb_month": self._validate_non_negative(storage_gb_month, "storage_gb_month"),
            "egress_gb": self._validate_non_negative(egress_gb, "egress_gb"),
        }

        default_rates = {
            "gpu_hours": 2.4,
            "queue_compute_hours": 0.55,
            "storage_gb_month": 0.09,
            "egress_gb": 0.12,
        }
        normalized_rates = dict(default_rates)
        for key, value in dict(rates or {}).items():
            metric = str(key).strip().lower()
            if not metric:
                continue
            normalized_rates[metric] = self._validate_non_negative(value, f"rates.{metric}")

        breakdown = {
            metric: round(usage.get(metric, 0.0) * normalized_rates.get(metric, 0.0), 6)
            for metric in ["gpu_hours", "queue_compute_hours", "storage_gb_month", "egress_gb"]
        }
        total_cost = round(sum(breakdown.values()), 6)

        trend_vs_previous: dict[str, float] = {
            "gpu_hours": 0.0,
            "queue_compute_hours": 0.0,
            "storage_gb_month": 0.0,
            "egress_gb": 0.0,
            "total_cost": 0.0,
        }
        previous = self._find_latest_snapshot(tenant_id=normalized_tenant)
        if previous is not None:
            prev_usage = dict(previous.get("usage", {}))
            prev_total = float(previous.get("total_cost", 0.0))
            for metric in ["gpu_hours", "queue_compute_hours", "storage_gb_month", "egress_gb"]:
                trend_vs_previous[metric] = round(
                    usage.get(metric, 0.0) - float(prev_usage.get(metric, 0.0)),
                    6,
                )
            trend_vs_previous["total_cost"] = round(total_cost - prev_total, 6)

        now = time.time()
        payload = {
            "snapshot_id": normalized_snapshot_id,
            "tenant_id": normalized_tenant,
            "period_start_day": validated_start_day,
            "period_end_day": validated_end_day,
            "usage": usage,
            "rates": normalized_rates,
            "cost_breakdown": breakdown,
            "total_cost": total_cost,
            "trend_vs_previous": trend_vs_previous,
            "metadata": {
                str(key): str(value)
                for key, value in dict(metadata or {}).items()
            },
            "updated_at": now,
        }
        self._snapshots[normalized_snapshot_id] = payload
        self._trim_snapshots(limit=5000)
        self._persist()
        return dict(payload)

    def get_snapshot(self, *, tenant_id: str, snapshot_id: str) -> dict[str, Any] | None:
        normalized_tenant = tenant_id.strip()
        normalized_snapshot_id = snapshot_id.strip().lower()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_snapshot_id:
            raise ValueError("snapshot_id must not be empty")

        payload = self._snapshots.get(normalized_snapshot_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def list_snapshots(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        items = [
            dict(item)
            for item in self._snapshots.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        items.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return items[:limit]

    def get_dashboard(
        self,
        *,
        tenant_id: str,
        lookback: int = 12,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if lookback <= 0:
            raise ValueError("lookback must be > 0")

        snapshots = self.list_snapshots(tenant_id=normalized_tenant, limit=lookback)
        if not snapshots:
            return {
                "tenant_id": normalized_tenant,
                "snapshot_count": 0,
                "totals": {
                    "gpu_cost": 0.0,
                    "queue_cost": 0.0,
                    "storage_cost": 0.0,
                    "egress_cost": 0.0,
                    "total_cost": 0.0,
                },
                "latest_total_cost": 0.0,
                "trend_total_cost": 0.0,
                "latest_snapshot": None,
            }

        gpu_cost = sum(float(item.get("cost_breakdown", {}).get("gpu_hours", 0.0)) for item in snapshots)
        queue_cost = sum(float(item.get("cost_breakdown", {}).get("queue_compute_hours", 0.0)) for item in snapshots)
        storage_cost = sum(float(item.get("cost_breakdown", {}).get("storage_gb_month", 0.0)) for item in snapshots)
        egress_cost = sum(float(item.get("cost_breakdown", {}).get("egress_gb", 0.0)) for item in snapshots)
        total_cost = sum(float(item.get("total_cost", 0.0)) for item in snapshots)

        latest = snapshots[0]
        trend_total_cost = float(latest.get("trend_vs_previous", {}).get("total_cost", 0.0))

        return {
            "tenant_id": normalized_tenant,
            "snapshot_count": len(snapshots),
            "totals": {
                "gpu_cost": round(gpu_cost, 6),
                "queue_cost": round(queue_cost, 6),
                "storage_cost": round(storage_cost, 6),
                "egress_cost": round(egress_cost, 6),
                "total_cost": round(total_cost, 6),
            },
            "latest_total_cost": float(latest.get("total_cost", 0.0)),
            "trend_total_cost": round(trend_total_cost, 6),
            "latest_snapshot": dict(latest),
        }

    def _find_latest_snapshot(self, *, tenant_id: str) -> dict[str, Any] | None:
        items = [
            dict(item)
            for item in self._snapshots.values()
            if str(item.get("tenant_id", "")) == tenant_id
        ]
        if not items:
            return None
        items.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return items[0]

    @staticmethod
    def _validate_non_negative(value: float, field_name: str) -> float:
        validated = float(value)
        if validated < 0:
            raise ValueError(f"{field_name} must be >= 0")
        return validated

    def _trim_snapshots(self, *, limit: int) -> None:
        if len(self._snapshots) <= limit:
            return

        items = sorted(
            self._snapshots.items(),
            key=lambda entry: float(entry[1].get("updated_at", 0.0)),
            reverse=True,
        )[:limit]
        self._snapshots = {key: dict(value) for key, value in items}

    def _persist(self) -> None:
        self._store.save({"snapshots": self._snapshots})
