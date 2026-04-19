"""Predictive autoscaling decisions based on queue depth and latency trends."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class PredictiveAutoscalingStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryPredictiveAutoscalingStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFilePredictiveAutoscalingStore:
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


class PredictiveAutoscalingService:
    def __init__(self, *, store: PredictiveAutoscalingStore | None = None) -> None:
        self._store = store or InMemoryPredictiveAutoscalingStore()
        payload = self._store.load()

        self._policies: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("policies", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

        raw_signals = payload.get("signals", {})
        self._signals: dict[str, list[dict[str, Any]]] = {}
        if isinstance(raw_signals, dict):
            for key, value in raw_signals.items():
                if not isinstance(key, str) or not isinstance(value, list):
                    continue
                self._signals[key] = [
                    dict(item)
                    for item in value
                    if isinstance(item, dict)
                ]

    def upsert_policy(
        self,
        *,
        policy_id: str,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        min_replicas: int,
        max_replicas: int,
        scale_up_step: int,
        scale_down_step: int,
        queue_depth_target: float,
        latency_ms_target: float,
        lookback_window: int = 6,
        cooldown_seconds: int = 0,
    ) -> dict[str, Any]:
        normalized_policy_id = policy_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        normalized_resource_type = resource_type.strip().lower()
        normalized_resource_id = resource_id.strip()

        if not normalized_policy_id:
            raise ValueError("policy_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if normalized_resource_type not in {"model", "worker"}:
            raise ValueError("resource_type must be one of model|worker")
        if not normalized_resource_id:
            raise ValueError("resource_id must not be empty")

        validated_min_replicas = self._validated_positive_int(min_replicas, "min_replicas")
        validated_max_replicas = self._validated_positive_int(max_replicas, "max_replicas")
        if validated_max_replicas < validated_min_replicas:
            raise ValueError("max_replicas must be greater than or equal to min_replicas")

        validated_scale_up_step = self._validated_positive_int(scale_up_step, "scale_up_step")
        validated_scale_down_step = self._validated_positive_int(scale_down_step, "scale_down_step")
        validated_queue_target = self._validated_positive_float(queue_depth_target, "queue_depth_target")
        validated_latency_target = self._validated_positive_float(latency_ms_target, "latency_ms_target")
        validated_lookback_window = self._validated_minimum_int(lookback_window, "lookback_window", 2)
        validated_cooldown = self._validated_non_negative_int(cooldown_seconds, "cooldown_seconds")

        previous = self._policies.get(normalized_policy_id)
        now = time.time()
        self._policies[normalized_policy_id] = {
            "policy_id": normalized_policy_id,
            "tenant_id": normalized_tenant,
            "resource_type": normalized_resource_type,
            "resource_id": normalized_resource_id,
            "min_replicas": validated_min_replicas,
            "max_replicas": validated_max_replicas,
            "scale_up_step": validated_scale_up_step,
            "scale_down_step": validated_scale_down_step,
            "queue_depth_target": validated_queue_target,
            "latency_ms_target": validated_latency_target,
            "lookback_window": validated_lookback_window,
            "cooldown_seconds": validated_cooldown,
            "last_recommendation_at": (
                None
                if previous is None
                else previous.get("last_recommendation_at")
            ),
            "last_direction": (
                None
                if previous is None
                else previous.get("last_direction")
            ),
            "last_desired_replicas": (
                None
                if previous is None
                else previous.get("last_desired_replicas")
            ),
            "updated_at": now,
        }

        self._persist()
        return dict(self._policies[normalized_policy_id])

    def list_policies(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        normalized_tenant = None if tenant_id is None else tenant_id.strip()
        items: list[dict[str, Any]] = []
        for key in sorted(self._policies.keys()):
            policy = self._policies[key]
            if normalized_tenant and str(policy.get("tenant_id", "")) != normalized_tenant:
                continue
            items.append(dict(policy))
        return items

    def ingest_signal(
        self,
        *,
        policy_id: str,
        tenant_id: str,
        queue_depth: float,
        latency_ms: float,
        observed_at: float | None = None,
    ) -> dict[str, Any]:
        policy = self._get_policy_for_tenant(policy_id=policy_id, tenant_id=tenant_id)

        sample = {
            "queue_depth": self._validated_non_negative_float(queue_depth, "queue_depth"),
            "latency_ms": self._validated_non_negative_float(latency_ms, "latency_ms"),
            "observed_at": time.time() if observed_at is None else float(observed_at),
        }

        normalized_policy_id = str(policy.get("policy_id"))
        history = self._signals.setdefault(normalized_policy_id, [])
        history.append(sample)
        if len(history) > 1000:
            del history[:-1000]

        self._persist()
        return self._signal_status(policy)

    def status(self, *, policy_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_policy_id = policy_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_policy_id or not normalized_tenant:
            raise ValueError("policy_id and tenant_id must not be empty")

        policy = self._policies.get(normalized_policy_id)
        if policy is None:
            return None
        if str(policy.get("tenant_id", "")) != normalized_tenant:
            return None
        return self._signal_status(policy)

    def recommend(
        self,
        *,
        policy_id: str,
        tenant_id: str,
        current_replicas: int,
    ) -> dict[str, Any]:
        policy = self._get_policy_for_tenant(policy_id=policy_id, tenant_id=tenant_id)
        status = self._signal_status(policy)
        if status["sample_count"] <= 0:
            raise ValueError("at least one signal sample is required before recommendation")

        validated_current = self._validated_non_negative_int(current_replicas, "current_replicas")
        min_replicas = int(policy["min_replicas"])
        max_replicas = int(policy["max_replicas"])
        bounded_current = max(min_replicas, min(max_replicas, validated_current))

        queue_pressure = float(status["queue_recent_mean"]) / max(float(policy["queue_depth_target"]), 1e-6)
        latency_pressure = float(status["latency_recent_mean"]) / max(float(policy["latency_ms_target"]), 1e-6)
        queue_trend = float(status["queue_trend"])
        latency_trend = float(status["latency_trend"])

        should_scale_up = (queue_pressure >= 1.1 or latency_pressure >= 1.1) and (queue_trend > 0 or latency_trend > 0)
        should_scale_down = (queue_pressure <= 0.7 and latency_pressure <= 0.75) and (queue_trend <= 0 and latency_trend <= 0)

        now = time.time()
        direction = "hold"
        desired_replicas = bounded_current
        reason = "within_target_band"

        if should_scale_up and bounded_current < max_replicas:
            direction = "scale_up"
            desired_replicas = min(max_replicas, bounded_current + int(policy["scale_up_step"]))
            reason = "queue_or_latency_above_target_with_upward_trend"
        elif should_scale_down and bounded_current > min_replicas:
            direction = "scale_down"
            desired_replicas = max(min_replicas, bounded_current - int(policy["scale_down_step"]))
            reason = "queue_and_latency_below_target_with_downward_trend"

        cooldown_seconds = int(policy["cooldown_seconds"])
        last_recommendation_at = policy.get("last_recommendation_at")
        if direction != "hold" and cooldown_seconds > 0 and last_recommendation_at is not None:
            elapsed = now - float(last_recommendation_at)
            if elapsed < cooldown_seconds:
                direction = "hold"
                desired_replicas = bounded_current
                reason = "cooldown_active"

        pressure_delta = max(abs(queue_pressure - 1.0), abs(latency_pressure - 1.0))
        queue_denominator = max(float(policy["queue_depth_target"]), 1e-6)
        latency_denominator = max(float(policy["latency_ms_target"]), 1e-6)
        trend_delta = max(abs(queue_trend) / queue_denominator, abs(latency_trend) / latency_denominator)
        confidence = min(1.0, 0.45 + (pressure_delta * 0.35) + (trend_delta * 0.20))
        if direction == "hold":
            confidence = min(confidence, 0.65)

        policy["last_recommendation_at"] = now
        policy["last_direction"] = direction
        policy["last_desired_replicas"] = desired_replicas
        self._persist()

        return {
            "policy_id": str(policy["policy_id"]),
            "tenant_id": str(policy["tenant_id"]),
            "resource_type": str(policy["resource_type"]),
            "resource_id": str(policy["resource_id"]),
            "direction": direction,
            "current_replicas": validated_current,
            "bounded_current_replicas": bounded_current,
            "desired_replicas": desired_replicas,
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
            "queue_pressure": round(queue_pressure, 6),
            "latency_pressure": round(latency_pressure, 6),
            "queue_trend": round(queue_trend, 6),
            "latency_trend": round(latency_trend, 6),
            "confidence": round(confidence, 6),
            "reason": reason,
            "evaluated_at": now,
        }

    def _get_policy_for_tenant(self, *, policy_id: str, tenant_id: str) -> dict[str, Any]:
        normalized_policy_id = policy_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_policy_id:
            raise ValueError("policy_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        policy = self._policies.get(normalized_policy_id)
        if policy is None:
            raise ValueError("policy not found")

        policy_tenant_id = str(policy.get("tenant_id", ""))
        if policy_tenant_id != normalized_tenant:
            raise ValueError("policy does not belong to tenant")
        return policy

    def _signal_status(self, policy: dict[str, Any]) -> dict[str, Any]:
        policy_id = str(policy.get("policy_id", ""))
        lookback_window = int(policy.get("lookback_window", 6))
        history = self._signals.get(policy_id, [])
        recent = history[-lookback_window:] if lookback_window > 0 else history

        sample_count = len(history)
        recent_count = len(recent)
        queue_recent_mean = (
            sum(float(sample.get("queue_depth", 0.0)) for sample in recent) / recent_count
            if recent_count > 0
            else 0.0
        )
        latency_recent_mean = (
            sum(float(sample.get("latency_ms", 0.0)) for sample in recent) / recent_count
            if recent_count > 0
            else 0.0
        )

        queue_trend = 0.0
        latency_trend = 0.0
        if recent_count >= 2:
            queue_trend = float(recent[-1].get("queue_depth", 0.0)) - float(recent[0].get("queue_depth", 0.0))
            latency_trend = float(recent[-1].get("latency_ms", 0.0)) - float(recent[0].get("latency_ms", 0.0))

        last_observed_at = None
        if history:
            last_observed_at = float(history[-1].get("observed_at", 0.0))

        return {
            "policy_id": policy_id,
            "tenant_id": str(policy.get("tenant_id", "")),
            "resource_type": str(policy.get("resource_type", "")),
            "resource_id": str(policy.get("resource_id", "")),
            "sample_count": sample_count,
            "recent_sample_count": recent_count,
            "queue_recent_mean": queue_recent_mean,
            "latency_recent_mean": latency_recent_mean,
            "queue_trend": queue_trend,
            "latency_trend": latency_trend,
            "last_observed_at": last_observed_at,
            "last_direction": policy.get("last_direction"),
            "last_desired_replicas": policy.get("last_desired_replicas"),
            "updated_at": float(policy.get("updated_at", 0.0)),
        }

    @staticmethod
    def _validated_positive_int(value: int, field_name: str) -> int:
        numeric = int(value)
        if numeric <= 0:
            raise ValueError(f"{field_name} must be positive")
        return numeric

    @staticmethod
    def _validated_minimum_int(value: int, field_name: str, minimum: int) -> int:
        numeric = int(value)
        if numeric < minimum:
            raise ValueError(f"{field_name} must be greater than or equal to {minimum}")
        return numeric

    @staticmethod
    def _validated_non_negative_int(value: int, field_name: str) -> int:
        numeric = int(value)
        if numeric < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return numeric

    @staticmethod
    def _validated_positive_float(value: float, field_name: str) -> float:
        numeric = float(value)
        if numeric <= 0:
            raise ValueError(f"{field_name} must be positive")
        return numeric

    @staticmethod
    def _validated_non_negative_float(value: float, field_name: str) -> float:
        numeric = float(value)
        if numeric < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return numeric

    def _persist(self) -> None:
        self._store.save(
            {
                "policies": self._policies,
                "signals": self._signals,
            }
        )
