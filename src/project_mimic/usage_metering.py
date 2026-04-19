"""Tenant usage metering for billable dimensions."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class UsageMeteringStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryUsageMeteringStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {key: dict(item) for key, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {key: dict(item) for key, item in self._payload.items()}


class JsonFileUsageMeteringStore:
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
        for key, payload in loaded.items():
            if isinstance(key, str) and isinstance(payload, dict):
                result[key] = dict(payload)
        return result


class TenantUsageMetering:
    def __init__(self, *, store: UsageMeteringStore | None = None) -> None:
        self._store = store or InMemoryUsageMeteringStore()
        self._records = self._store.load()

    def record(
        self,
        *,
        tenant_id: str,
        dimension: str,
        units: float = 1.0,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_dimension = dimension.strip()
        if not normalized_dimension:
            raise ValueError("dimension must not be empty")

        if units <= 0:
            raise ValueError("units must be > 0")

        recorded_at = time.time() if timestamp is None else float(timestamp)
        day_bucket = int(recorded_at) // 86400
        key = f"{normalized_tenant}::{normalized_dimension}::{day_bucket}"

        existing = self._records.get(key)
        next_units = float(units)
        created_at = recorded_at
        if existing is not None:
            next_units += float(existing.get("units", 0.0))
            created_at = float(existing.get("created_at", recorded_at))

        payload = {
            "record_key": key,
            "tenant_id": normalized_tenant,
            "dimension": normalized_dimension,
            "day_bucket": day_bucket,
            "units": next_units,
            "created_at": created_at,
            "updated_at": recorded_at,
        }
        self._records[key] = payload
        self._persist()
        return dict(payload)

    def list_records(
        self,
        *,
        tenant_id: str | None = None,
        dimension: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        selected: list[dict[str, Any]] = []
        for payload in self._records.values():
            if tenant_id is not None and str(payload.get("tenant_id")) != tenant_id:
                continue
            if dimension is not None and str(payload.get("dimension")) != dimension:
                continue
            selected.append(dict(payload))

        selected.sort(
            key=lambda item: (
                int(item.get("day_bucket", 0)),
                float(item.get("updated_at", 0.0)),
            ),
            reverse=True,
        )
        return selected[:limit]

    def summarize(
        self,
        *,
        tenant_id: str,
        start_day: int | None = None,
        end_day: int | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        dimensions: dict[str, float] = {}
        total_units = 0.0

        for payload in self._records.values():
            if str(payload.get("tenant_id")) != normalized_tenant:
                continue

            day_bucket = int(payload.get("day_bucket", 0))
            if start_day is not None and day_bucket < start_day:
                continue
            if end_day is not None and day_bucket > end_day:
                continue

            dimension = str(payload.get("dimension", "unknown"))
            units = float(payload.get("units", 0.0))
            dimensions[dimension] = dimensions.get(dimension, 0.0) + units
            total_units += units

        return {
            "tenant_id": normalized_tenant,
            "start_day": start_day,
            "end_day": end_day,
            "dimensions": dimensions,
            "total_units": total_units,
        }

    def _persist(self) -> None:
        self._store.save(self._records)
