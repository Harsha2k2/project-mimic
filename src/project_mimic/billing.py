"""Billing primitives for plan limits and overage protection."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class BillingStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryBillingStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = dict(payload)

    def load(self) -> dict[str, Any]:
        return dict(self._payload)


class JsonFileBillingStore:
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


class BillingPrimitives:
    def __init__(self, *, store: BillingStore | None = None) -> None:
        self._store = store or InMemoryBillingStore()
        payload = self._store.load()

        plans_payload = payload.get("plans", {}) if isinstance(payload, dict) else {}
        subs_payload = payload.get("subscriptions", {}) if isinstance(payload, dict) else {}

        self._plans: dict[str, dict[str, Any]] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}

        if isinstance(plans_payload, dict):
            for plan_id, plan in plans_payload.items():
                if isinstance(plan_id, str) and isinstance(plan, dict):
                    self._plans[plan_id] = dict(plan)

        if isinstance(subs_payload, dict):
            for tenant_id, sub in subs_payload.items():
                if isinstance(tenant_id, str) and isinstance(sub, dict):
                    self._subscriptions[tenant_id] = dict(sub)

    def upsert_plan(
        self,
        *,
        plan_id: str,
        description: str,
        included_units: dict[str, float],
        hard_limits: bool,
        overage_buffer_units: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        normalized_plan_id = plan_id.strip()
        if not normalized_plan_id:
            raise ValueError("plan_id must not be empty")

        normalized_limits = self._normalize_dimensions(included_units)
        normalized_buffer = self._normalize_dimensions(overage_buffer_units or {})

        now = time.time()
        existing = self._plans.get(normalized_plan_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "plan_id": normalized_plan_id,
            "description": description,
            "included_units": normalized_limits,
            "hard_limits": bool(hard_limits),
            "overage_buffer_units": normalized_buffer,
            "created_at": created_at,
            "updated_at": now,
        }
        self._plans[normalized_plan_id] = payload
        self._persist()
        return dict(payload)

    def list_plans(self) -> list[dict[str, Any]]:
        return [dict(self._plans[plan_id]) for plan_id in sorted(self._plans.keys())]

    def get_plan(self, *, plan_id: str) -> dict[str, Any]:
        payload = self._plans.get(plan_id)
        if payload is None:
            raise KeyError(plan_id)
        return dict(payload)

    def assign_plan(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        overage_protection: bool = True,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        if plan_id not in self._plans:
            raise KeyError(plan_id)

        now = time.time()
        existing = self._subscriptions.get(normalized_tenant)
        started_at = now if existing is None else float(existing.get("started_at", now))

        payload = {
            "tenant_id": normalized_tenant,
            "plan_id": plan_id,
            "overage_protection": bool(overage_protection),
            "started_at": started_at,
            "updated_at": now,
        }
        self._subscriptions[normalized_tenant] = payload
        self._persist()
        return dict(payload)

    def get_subscription(self, *, tenant_id: str) -> dict[str, Any]:
        payload = self._subscriptions.get(tenant_id)
        if payload is None:
            raise KeyError(tenant_id)
        return dict(payload)

    def check_overage(
        self,
        *,
        tenant_id: str,
        usage_dimensions: dict[str, float],
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_usage = self._normalize_dimensions(usage_dimensions)
        subscription = self._subscriptions.get(normalized_tenant)
        if subscription is None:
            return {
                "tenant_id": normalized_tenant,
                "plan_id": None,
                "overage_protection": False,
                "usage_dimensions": normalized_usage,
                "limits": {},
                "overage_buffer_units": {},
                "exceeded_dimensions": {},
                "blocked_dimensions": [],
                "blocked": False,
                "within_limits": True,
            }

        plan = self._plans.get(str(subscription.get("plan_id", "")))
        if plan is None:
            return {
                "tenant_id": normalized_tenant,
                "plan_id": str(subscription.get("plan_id", "")),
                "overage_protection": bool(subscription.get("overage_protection", True)),
                "usage_dimensions": normalized_usage,
                "limits": {},
                "overage_buffer_units": {},
                "exceeded_dimensions": {},
                "blocked_dimensions": [],
                "blocked": False,
                "within_limits": True,
            }

        limits = self._normalize_dimensions(dict(plan.get("included_units", {})))
        buffers = self._normalize_dimensions(dict(plan.get("overage_buffer_units", {})))
        overage_protection = bool(subscription.get("overage_protection", True))
        hard_limits = bool(plan.get("hard_limits", True))

        exceeded: dict[str, float] = {}
        blocked_dimensions: list[str] = []

        for dimension, limit in limits.items():
            used = normalized_usage.get(dimension, 0.0)
            if used <= limit:
                continue

            exceeded[dimension] = used - limit
            allowed_with_buffer = limit + buffers.get(dimension, 0.0)
            if overage_protection and hard_limits and used > allowed_with_buffer:
                blocked_dimensions.append(dimension)

        return {
            "tenant_id": normalized_tenant,
            "plan_id": str(subscription.get("plan_id", "")),
            "overage_protection": overage_protection,
            "usage_dimensions": normalized_usage,
            "limits": limits,
            "overage_buffer_units": buffers,
            "exceeded_dimensions": exceeded,
            "blocked_dimensions": blocked_dimensions,
            "blocked": bool(blocked_dimensions),
            "within_limits": len(exceeded) == 0,
        }

    def monthly_report(
        self,
        *,
        tenant_id: str,
        month: str,
        usage_dimensions: dict[str, float],
    ) -> dict[str, Any]:
        status = self.check_overage(tenant_id=tenant_id, usage_dimensions=usage_dimensions)
        status["month"] = month
        status["generated_at"] = time.time()
        return status

    @staticmethod
    def _normalize_dimensions(payload: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, value in payload.items():
            dimension = str(key).strip()
            if not dimension:
                continue
            units = float(value)
            if units < 0:
                raise ValueError("dimension units must be >= 0")
            normalized[dimension] = units
        return normalized

    def _persist(self) -> None:
        self._store.save({"plans": self._plans, "subscriptions": self._subscriptions})
