"""Benchmark lab for reproducible cross-version comparisons."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any, Protocol


class BenchmarkLabStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryBenchmarkLabStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileBenchmarkLabStore:
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


class BenchmarkLabService:
    def __init__(self, *, store: BenchmarkLabStore | None = None) -> None:
        self._store = store or InMemoryBenchmarkLabStore()
        payload = self._store.load()
        self._suites: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("suites", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._runs: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("runs", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_suite(
        self,
        *,
        suite_id: str,
        name: str,
        description: str,
        task_ids: list[str],
        score_regression_threshold: float = 0.02,
        latency_regression_threshold_ms: float = 40.0,
        sample_count: int = 3,
        deterministic_seed: int = 42,
        active: bool = True,
    ) -> dict[str, Any]:
        normalized_suite_id = suite_id.strip().lower()
        if not normalized_suite_id:
            raise ValueError("suite_id must not be empty")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name must not be empty")

        normalized_description = description.strip()
        if not normalized_description:
            raise ValueError("description must not be empty")

        normalized_tasks = sorted({item.strip().lower() for item in task_ids if item.strip()})
        if not normalized_tasks:
            raise ValueError("task_ids must not be empty")

        validated_score_threshold = float(score_regression_threshold)
        if validated_score_threshold < 0:
            raise ValueError("score_regression_threshold must be >= 0")

        validated_latency_threshold = float(latency_regression_threshold_ms)
        if validated_latency_threshold < 0:
            raise ValueError("latency_regression_threshold_ms must be >= 0")

        validated_sample_count = int(sample_count)
        if validated_sample_count <= 0:
            raise ValueError("sample_count must be > 0")

        validated_seed = int(deterministic_seed)

        now = time.time()
        existing = self._suites.get(normalized_suite_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "suite_id": normalized_suite_id,
            "name": normalized_name,
            "description": normalized_description,
            "task_ids": normalized_tasks,
            "score_regression_threshold": validated_score_threshold,
            "latency_regression_threshold_ms": validated_latency_threshold,
            "sample_count": validated_sample_count,
            "deterministic_seed": validated_seed,
            "active": bool(active),
            "created_at": created_at,
            "updated_at": now,
        }
        self._suites[normalized_suite_id] = payload
        self._persist()
        return dict(payload)

    def get_suite(self, *, suite_id: str) -> dict[str, Any] | None:
        normalized_suite_id = suite_id.strip().lower()
        if not normalized_suite_id:
            raise ValueError("suite_id must not be empty")

        payload = self._suites.get(normalized_suite_id)
        if payload is None:
            return None
        return dict(payload)

    def list_suites(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        items = [dict(item) for item in self._suites.values()]
        if not include_inactive:
            items = [item for item in items if bool(item.get("active", False))]
        items.sort(key=lambda item: str(item.get("suite_id", "")))
        return items

    def run_comparison(
        self,
        *,
        tenant_id: str,
        run_id: str,
        suite_id: str,
        baseline_version: str,
        candidate_version: str,
        initiated_by: str,
        deterministic_seed: int | None = None,
        sample_count: int | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_run_id = run_id.strip().lower()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        if normalized_run_id in self._runs:
            raise ValueError("run already exists")

        normalized_suite_id = suite_id.strip().lower()
        if not normalized_suite_id:
            raise ValueError("suite_id must not be empty")

        suite = self._suites.get(normalized_suite_id)
        if suite is None:
            raise ValueError("suite not found")
        if not bool(suite.get("active", False)):
            raise ValueError("suite is inactive")

        normalized_baseline = baseline_version.strip()
        normalized_candidate = candidate_version.strip()
        if not normalized_baseline:
            raise ValueError("baseline_version must not be empty")
        if not normalized_candidate:
            raise ValueError("candidate_version must not be empty")

        normalized_initiated_by = initiated_by.strip()
        if not normalized_initiated_by:
            raise ValueError("initiated_by must not be empty")

        resolved_seed = int(
            suite.get("deterministic_seed", 42)
            if deterministic_seed is None
            else int(deterministic_seed)
        )
        resolved_samples = int(
            suite.get("sample_count", 3)
            if sample_count is None
            else int(sample_count)
        )
        if resolved_samples <= 0:
            raise ValueError("sample_count must be > 0")

        score_threshold = float(suite.get("score_regression_threshold", 0.02))
        latency_threshold = float(suite.get("latency_regression_threshold_ms", 40.0))

        started_at = time.time()
        task_comparisons: list[dict[str, Any]] = []
        regressions = 0
        improvements = 0

        task_ids = [str(item) for item in suite.get("task_ids", []) if isinstance(item, str)]
        for task_id in task_ids:
            baseline_scores: list[float] = []
            baseline_latency: list[float] = []
            candidate_scores: list[float] = []
            candidate_latency: list[float] = []

            for sample_index in range(resolved_samples):
                baseline_metric = self._simulate_metric(
                    version=normalized_baseline,
                    task_id=task_id,
                    seed=resolved_seed,
                    sample_index=sample_index,
                )
                candidate_metric = self._simulate_metric(
                    version=normalized_candidate,
                    task_id=task_id,
                    seed=resolved_seed,
                    sample_index=sample_index,
                )
                baseline_scores.append(float(baseline_metric["score"]))
                baseline_latency.append(float(baseline_metric["latency_ms"]))
                candidate_scores.append(float(candidate_metric["score"]))
                candidate_latency.append(float(candidate_metric["latency_ms"]))

            baseline_score_avg = sum(baseline_scores) / len(baseline_scores)
            candidate_score_avg = sum(candidate_scores) / len(candidate_scores)
            baseline_latency_avg = sum(baseline_latency) / len(baseline_latency)
            candidate_latency_avg = sum(candidate_latency) / len(candidate_latency)
            score_delta = round(candidate_score_avg - baseline_score_avg, 6)
            latency_delta = round(candidate_latency_avg - baseline_latency_avg, 6)

            score_regression = score_delta < -score_threshold
            latency_regression = latency_delta > latency_threshold
            if score_regression or latency_regression:
                status = "regression"
                regressions += 1
            elif score_delta > score_threshold or latency_delta < -latency_threshold:
                status = "improvement"
                improvements += 1
            else:
                status = "neutral"

            task_comparisons.append(
                {
                    "task_id": task_id,
                    "baseline_score": round(baseline_score_avg, 6),
                    "candidate_score": round(candidate_score_avg, 6),
                    "score_delta": score_delta,
                    "baseline_latency_ms": round(baseline_latency_avg, 6),
                    "candidate_latency_ms": round(candidate_latency_avg, 6),
                    "latency_delta_ms": latency_delta,
                    "score_regression": score_regression,
                    "latency_regression": latency_regression,
                    "status": status,
                }
            )

        score_delta_mean = 0.0
        latency_delta_mean = 0.0
        if task_comparisons:
            score_delta_mean = sum(float(item["score_delta"]) for item in task_comparisons) / len(task_comparisons)
            latency_delta_mean = sum(float(item["latency_delta_ms"]) for item in task_comparisons) / len(task_comparisons)

        fingerprint_payload = {
            "suite_id": normalized_suite_id,
            "baseline_version": normalized_baseline,
            "candidate_version": normalized_candidate,
            "seed": resolved_seed,
            "samples": resolved_samples,
            "task_comparisons": task_comparisons,
        }
        reproducibility_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]

        finished_at = time.time()
        payload = {
            "run_id": normalized_run_id,
            "tenant_id": normalized_tenant,
            "suite_id": normalized_suite_id,
            "baseline_version": normalized_baseline,
            "candidate_version": normalized_candidate,
            "initiated_by": normalized_initiated_by,
            "deterministic_seed": resolved_seed,
            "sample_count": resolved_samples,
            "task_comparisons": task_comparisons,
            "regression_count": regressions,
            "improvement_count": improvements,
            "score_delta_mean": round(score_delta_mean, 6),
            "latency_delta_mean_ms": round(latency_delta_mean, 6),
            "status": "regression_detected" if regressions > 0 else "pass",
            "reproducibility_fingerprint": reproducibility_fingerprint,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        self._runs[normalized_run_id] = payload
        self._trim_runs(limit=4000)
        self._persist()
        return dict(payload)

    def list_runs(
        self,
        *,
        tenant_id: str,
        suite_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        normalized_suite_id = suite_id.strip().lower() if suite_id is not None else ""
        normalized_status = status.strip().lower() if status is not None else ""

        items = [
            dict(item)
            for item in self._runs.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        if normalized_suite_id:
            items = [item for item in items if str(item.get("suite_id", "")) == normalized_suite_id]
        if normalized_status:
            items = [item for item in items if str(item.get("status", "")).lower() == normalized_status]

        items.sort(key=lambda item: float(item.get("started_at", 0.0)), reverse=True)
        return items[:limit]

    def get_run(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_run_id = run_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._runs.get(normalized_run_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    @staticmethod
    def _simulate_metric(
        *,
        version: str,
        task_id: str,
        seed: int,
        sample_index: int,
    ) -> dict[str, float]:
        material = f"{version}|{task_id}|{seed}|{sample_index}".encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()

        score_bucket = int(digest[:8], 16)
        latency_bucket = int(digest[8:16], 16)

        score = 0.78 + ((score_bucket % 1800) / 10000.0)
        latency_ms = 120.0 + float(latency_bucket % 220)
        return {
            "score": round(min(score, 1.0), 6),
            "latency_ms": round(latency_ms, 6),
        }

    def _trim_runs(self, *, limit: int) -> None:
        if len(self._runs) <= limit:
            return

        items = sorted(
            self._runs.items(),
            key=lambda entry: float(entry[1].get("started_at", 0.0)),
            reverse=True,
        )[:limit]
        self._runs = {key: dict(value) for key, value in items}

    def _persist(self) -> None:
        self._store.save({"suites": self._suites, "runs": self._runs})
