"""Cost-aware scheduling for model and worker routing decisions."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class CostAwareSchedulerStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryCostAwareSchedulerStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileCostAwareSchedulerStore:
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


class CostAwareScheduler:
    def __init__(self, *, store: CostAwareSchedulerStore | None = None) -> None:
        self._store = store or InMemoryCostAwareSchedulerStore()
        payload = self._store.load()
        self._model_profiles: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("model_profiles", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._worker_profiles: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("worker_profiles", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_model_profile(
        self,
        *,
        candidate_id: str,
        model_id: str,
        region: str,
        cost_per_1k_tokens: float,
        latency_ms: float,
        queue_depth: int,
        quality_score: float,
    ) -> dict[str, Any]:
        normalized_id = candidate_id.strip().lower()
        if not normalized_id:
            raise ValueError("candidate_id must not be empty")

        normalized_model_id = model_id.strip()
        normalized_region = region.strip().lower()
        if not normalized_model_id:
            raise ValueError("model_id must not be empty")
        if not normalized_region:
            raise ValueError("region must not be empty")

        self._model_profiles[normalized_id] = {
            "candidate_id": normalized_id,
            "model_id": normalized_model_id,
            "region": normalized_region,
            "cost_per_1k_tokens": self._validated_non_negative(cost_per_1k_tokens, "cost_per_1k_tokens"),
            "latency_ms": self._validated_non_negative(latency_ms, "latency_ms"),
            "queue_depth": self._validated_non_negative_int(queue_depth, "queue_depth"),
            "quality_score": self._validated_quality_score(quality_score),
            "updated_at": time.time(),
        }
        self._persist()
        return dict(self._model_profiles[normalized_id])

    def upsert_worker_profile(
        self,
        *,
        candidate_id: str,
        worker_pool: str,
        region: str,
        cost_per_minute: float,
        latency_ms: float,
        queue_depth: int,
        reliability_score: float,
    ) -> dict[str, Any]:
        normalized_id = candidate_id.strip().lower()
        if not normalized_id:
            raise ValueError("candidate_id must not be empty")

        normalized_pool = worker_pool.strip()
        normalized_region = region.strip().lower()
        if not normalized_pool:
            raise ValueError("worker_pool must not be empty")
        if not normalized_region:
            raise ValueError("region must not be empty")

        self._worker_profiles[normalized_id] = {
            "candidate_id": normalized_id,
            "worker_pool": normalized_pool,
            "region": normalized_region,
            "cost_per_minute": self._validated_non_negative(cost_per_minute, "cost_per_minute"),
            "latency_ms": self._validated_non_negative(latency_ms, "latency_ms"),
            "queue_depth": self._validated_non_negative_int(queue_depth, "queue_depth"),
            "reliability_score": self._validated_quality_score(reliability_score),
            "updated_at": time.time(),
        }
        self._persist()
        return dict(self._worker_profiles[normalized_id])

    def list_model_profiles(self) -> list[dict[str, Any]]:
        return [dict(self._model_profiles[key]) for key in sorted(self._model_profiles.keys())]

    def list_worker_profiles(self) -> list[dict[str, Any]]:
        return [dict(self._worker_profiles[key]) for key in sorted(self._worker_profiles.keys())]

    def schedule_model(
        self,
        *,
        tenant_id: str,
        objective: str = "balanced",
    ) -> dict[str, Any]:
        if not self._model_profiles:
            raise ValueError("no model profiles available for scheduling")

        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_objective = objective.strip().lower() or "balanced"
        if normalized_objective not in {"balanced", "min_cost", "low_latency"}:
            raise ValueError("objective must be one of balanced|min_cost|low_latency")

        scored = [
            self._score_model_candidate(payload, objective=normalized_objective)
            for payload in self._model_profiles.values()
        ]
        scored.sort(key=lambda item: (item["score"], item["candidate_id"]))
        best = scored[0]
        return {
            "tenant_id": normalized_tenant,
            "objective": normalized_objective,
            "selected_candidate": best["candidate_id"],
            "model_id": best["model_id"],
            "region": best["region"],
            "score": round(best["score"], 6),
            "routed_at": time.time(),
            "rationale": best["rationale"],
        }

    def schedule_worker(
        self,
        *,
        tenant_id: str,
        objective: str = "balanced",
    ) -> dict[str, Any]:
        if not self._worker_profiles:
            raise ValueError("no worker profiles available for scheduling")

        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_objective = objective.strip().lower() or "balanced"
        if normalized_objective not in {"balanced", "min_cost", "low_latency"}:
            raise ValueError("objective must be one of balanced|min_cost|low_latency")

        scored = [
            self._score_worker_candidate(payload, objective=normalized_objective)
            for payload in self._worker_profiles.values()
        ]
        scored.sort(key=lambda item: (item["score"], item["candidate_id"]))
        best = scored[0]
        return {
            "tenant_id": normalized_tenant,
            "objective": normalized_objective,
            "selected_candidate": best["candidate_id"],
            "worker_pool": best["worker_pool"],
            "region": best["region"],
            "score": round(best["score"], 6),
            "routed_at": time.time(),
            "rationale": best["rationale"],
        }

    def _score_model_candidate(self, payload: dict[str, Any], *, objective: str) -> dict[str, Any]:
        cost = float(payload.get("cost_per_1k_tokens", 0.0))
        latency = float(payload.get("latency_ms", 0.0))
        queue_depth = int(payload.get("queue_depth", 0))
        quality = float(payload.get("quality_score", 0.0))

        score = self._weighted_score(
            cost=cost,
            latency=latency,
            queue_depth=queue_depth,
            quality_or_reliability=quality,
            objective=objective,
        )
        return {
            "candidate_id": str(payload.get("candidate_id", "")),
            "model_id": str(payload.get("model_id", "")),
            "region": str(payload.get("region", "")),
            "score": score,
            "rationale": {
                "cost_per_1k_tokens": cost,
                "latency_ms": latency,
                "queue_depth": queue_depth,
                "quality_score": quality,
            },
        }

    def _score_worker_candidate(self, payload: dict[str, Any], *, objective: str) -> dict[str, Any]:
        cost = float(payload.get("cost_per_minute", 0.0))
        latency = float(payload.get("latency_ms", 0.0))
        queue_depth = int(payload.get("queue_depth", 0))
        reliability = float(payload.get("reliability_score", 0.0))

        score = self._weighted_score(
            cost=cost,
            latency=latency,
            queue_depth=queue_depth,
            quality_or_reliability=reliability,
            objective=objective,
        )
        return {
            "candidate_id": str(payload.get("candidate_id", "")),
            "worker_pool": str(payload.get("worker_pool", "")),
            "region": str(payload.get("region", "")),
            "score": score,
            "rationale": {
                "cost_per_minute": cost,
                "latency_ms": latency,
                "queue_depth": queue_depth,
                "reliability_score": reliability,
            },
        }

    @staticmethod
    def _weighted_score(
        *,
        cost: float,
        latency: float,
        queue_depth: int,
        quality_or_reliability: float,
        objective: str,
    ) -> float:
        # Normalize heterogeneous signals so milliseconds and queue depth do not dwarf cost.
        normalized_cost = cost / 10.0
        normalized_latency = latency / 1000.0
        normalized_queue_depth = float(queue_depth) / 100.0
        quality_penalty = 1.0 - quality_or_reliability
        if objective == "min_cost":
            return (
                (normalized_cost * 0.85)
                + (normalized_latency * 0.05)
                + (normalized_queue_depth * 0.05)
                + (quality_penalty * 0.05)
            )
        if objective == "low_latency":
            return (
                (normalized_cost * 0.05)
                + (normalized_latency * 0.75)
                + (normalized_queue_depth * 0.15)
                + (quality_penalty * 0.05)
            )
        return (
            (normalized_cost * 0.40)
            + (normalized_latency * 0.35)
            + (normalized_queue_depth * 0.20)
            + (quality_penalty * 0.05)
        )

    @staticmethod
    def _validated_non_negative(value: float, field_name: str) -> float:
        numeric = float(value)
        if numeric < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return numeric

    @staticmethod
    def _validated_non_negative_int(value: int, field_name: str) -> int:
        numeric = int(value)
        if numeric < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return numeric

    @staticmethod
    def _validated_quality_score(value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        return numeric

    def _persist(self) -> None:
        self._store.save(
            {
                "model_profiles": self._model_profiles,
                "worker_profiles": self._worker_profiles,
            }
        )
