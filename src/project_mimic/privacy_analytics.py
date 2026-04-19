"""Privacy-preserving analytics for tenant-scoped reporting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class PrivacyAnalyticsStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryPrivacyAnalyticsStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFilePrivacyAnalyticsStore:
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


class PrivacyPreservingAnalyticsService:
    def __init__(self, *, store: PrivacyAnalyticsStore | None = None) -> None:
        self._store = store or InMemoryPrivacyAnalyticsStore()
        loaded = self._store.load()
        self._policies: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("policies", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._events: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("events", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._reports: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("reports", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_policy(
        self,
        *,
        tenant_id: str,
        epsilon: float,
        min_group_size: int,
        max_groups: int,
        redact_dimension_keys: list[str] | None = None,
        noise_seed: str | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        validated_epsilon = float(epsilon)
        if validated_epsilon <= 0.0:
            raise ValueError("epsilon must be > 0")

        validated_min_group_size = int(min_group_size)
        if validated_min_group_size <= 0:
            raise ValueError("min_group_size must be > 0")

        validated_max_groups = int(max_groups)
        if validated_max_groups <= 0:
            raise ValueError("max_groups must be > 0")

        normalized_redact_keys = sorted(
            {
                item.strip().lower()
                for item in (redact_dimension_keys or [])
                if item.strip()
            }
        )
        normalized_noise_seed = (
            noise_seed.strip()
            if noise_seed is not None and noise_seed.strip()
            else normalized_tenant
        )

        now = time.time()
        existing = self._policies.get(normalized_tenant)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "tenant_id": normalized_tenant,
            "epsilon": validated_epsilon,
            "min_group_size": validated_min_group_size,
            "max_groups": validated_max_groups,
            "redact_dimension_keys": normalized_redact_keys,
            "noise_seed": normalized_noise_seed,
            "created_at": created_at,
            "updated_at": now,
        }
        self._policies[normalized_tenant] = payload
        self._persist()
        return dict(payload)

    def get_policy(self, *, tenant_id: str) -> dict[str, Any] | None:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._policies.get(normalized_tenant)
        if payload is None:
            return None
        return dict(payload)

    def list_policies(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        items = [dict(item) for item in self._policies.values()]
        items.sort(key=lambda item: str(item.get("tenant_id", "")))
        return items[:limit]

    def ingest_event(
        self,
        *,
        tenant_id: str,
        metric_name: str,
        value: float,
        dimensions: dict[str, str] | None = None,
        observed_at: float | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_metric_name = metric_name.strip().lower()
        if not normalized_metric_name:
            raise ValueError("metric_name must not be empty")

        validated_value = float(value)
        if validated_value < 0.0:
            raise ValueError("value must be >= 0")

        normalized_dimensions = {
            str(key).strip().lower(): str(raw_value).strip()
            for key, raw_value in dict(dimensions or {}).items()
            if str(key).strip()
        }

        event_id = f"pae_{uuid4().hex[:12]}"
        event = {
            "event_id": event_id,
            "tenant_id": normalized_tenant,
            "metric_name": normalized_metric_name,
            "value": validated_value,
            "dimensions": normalized_dimensions,
            "observed_at": time.time() if observed_at is None else float(observed_at),
        }
        self._events[event_id] = event
        self._trim_events(limit=20000)
        self._persist()
        return dict(event)

    def generate_report(
        self,
        *,
        tenant_id: str,
        metric_name: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_metric_name = metric_name.strip().lower() if metric_name is not None else ""
        normalized_group_by = [
            item.strip().lower()
            for item in (group_by or [])
            if item.strip()
        ]

        policy = self._policies.get(
            normalized_tenant,
            {
                "tenant_id": normalized_tenant,
                "epsilon": 1.0,
                "min_group_size": 3,
                "max_groups": 200,
                "redact_dimension_keys": [],
                "noise_seed": normalized_tenant,
            },
        )

        report_groups: dict[str, dict[str, Any]] = {}
        total_events = 0

        for event in self._events.values():
            if str(event.get("tenant_id", "")) != normalized_tenant:
                continue

            event_metric = str(event.get("metric_name", "")).strip().lower()
            if normalized_metric_name and event_metric != normalized_metric_name:
                continue

            observed_at = float(event.get("observed_at", 0.0))
            if start_time is not None and observed_at < float(start_time):
                continue
            if end_time is not None and observed_at > float(end_time):
                continue

            dimensions = {
                str(key): str(value)
                for key, value in dict(event.get("dimensions", {})).items()
            }
            group_payload = {key: dimensions.get(key, "unknown") for key in normalized_group_by}
            group_key = json.dumps(group_payload, sort_keys=True)

            existing = report_groups.get(group_key)
            if existing is None:
                existing = {
                    "group": group_payload,
                    "count": 0,
                    "true_sum": 0.0,
                }
                report_groups[group_key] = existing

            existing["count"] = int(existing.get("count", 0)) + 1
            existing["true_sum"] = float(existing.get("true_sum", 0.0)) + float(event.get("value", 0.0))
            total_events += 1

        grouped = list(report_groups.values())
        grouped.sort(key=lambda item: int(item.get("count", 0)), reverse=True)
        grouped = grouped[: int(policy.get("max_groups", 200))]

        visible_groups: list[dict[str, Any]] = []
        suppressed_groups = 0
        min_group_size = int(policy.get("min_group_size", 3))
        redact_keys = {
            str(item).strip().lower()
            for item in policy.get("redact_dimension_keys", [])
            if str(item).strip()
        }

        for item in grouped:
            count = int(item.get("count", 0))
            if count < min_group_size:
                suppressed_groups += 1
                continue

            true_sum = float(item.get("true_sum", 0.0))
            group_payload = {
                str(key): (
                    "[redacted]"
                    if str(key).strip().lower() in redact_keys
                    else str(value)
                )
                for key, value in dict(item.get("group", {})).items()
            }
            group_key = json.dumps(group_payload, sort_keys=True)
            noise = self._deterministic_noise(
                seed=str(policy.get("noise_seed", normalized_tenant)),
                key=f"{normalized_tenant}:{normalized_metric_name}:{group_key}:{count}",
                epsilon=float(policy.get("epsilon", 1.0)),
            )
            noisy_sum = max(0.0, true_sum + noise)
            visible_groups.append(
                {
                    "group": group_payload,
                    "count": count,
                    "true_sum": true_sum,
                    "noisy_sum": noisy_sum,
                    "average": (true_sum / count) if count > 0 else 0.0,
                    "noisy_average": (noisy_sum / count) if count > 0 else 0.0,
                    "noise": noise,
                }
            )

        report_id = f"par_{uuid4().hex[:12]}"
        report = {
            "report_id": report_id,
            "tenant_id": normalized_tenant,
            "metric_name": normalized_metric_name or None,
            "start_time": None if start_time is None else float(start_time),
            "end_time": None if end_time is None else float(end_time),
            "group_by": normalized_group_by,
            "total_events": total_events,
            "visible_groups": len(visible_groups),
            "suppressed_groups": suppressed_groups,
            "epsilon": float(policy.get("epsilon", 1.0)),
            "min_group_size": min_group_size,
            "groups": visible_groups,
            "generated_at": time.time(),
        }

        self._reports[report_id] = report
        self._trim_reports(limit=2000)
        self._persist()
        return dict(report)

    def list_reports(self, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        items = [
            dict(item)
            for item in self._reports.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        items.sort(key=lambda item: float(item.get("generated_at", 0.0)), reverse=True)
        return items[:limit]

    def get_report(self, *, report_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_report_id = report_id.strip()
        normalized_tenant = tenant_id.strip()
        if not normalized_report_id:
            raise ValueError("report_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        report = self._reports.get(normalized_report_id)
        if report is None:
            return None
        if str(report.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(report)

    def _deterministic_noise(self, *, seed: str, key: str, epsilon: float) -> float:
        normalized_seed = seed.strip() or "default"
        normalized_key = key.strip() or "group"
        raw = hashlib.sha256(f"{normalized_seed}:{normalized_key}".encode("utf-8")).digest()
        bucket = int.from_bytes(raw[:8], "big") % 2001
        centered = (bucket - 1000) / 1000.0
        return centered / max(epsilon, 1e-6)

    def _trim_events(self, *, limit: int) -> None:
        if len(self._events) <= limit:
            return

        items = sorted(
            self._events.items(),
            key=lambda entry: float(entry[1].get("observed_at", 0.0)),
            reverse=True,
        )[:limit]
        self._events = {key: dict(value) for key, value in items}

    def _trim_reports(self, *, limit: int) -> None:
        if len(self._reports) <= limit:
            return

        items = sorted(
            self._reports.items(),
            key=lambda entry: float(entry[1].get("generated_at", 0.0)),
            reverse=True,
        )[:limit]
        self._reports = {key: dict(value) for key, value in items}

    def _persist(self) -> None:
        self._store.save(
            {
                "policies": self._policies,
                "events": self._events,
                "reports": self._reports,
            }
        )
