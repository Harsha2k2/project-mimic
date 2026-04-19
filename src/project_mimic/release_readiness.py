"""Release readiness scorecard generated from CI evidence."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class ReleaseReadinessStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryReleaseReadinessStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileReleaseReadinessStore:
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


class ReleaseReadinessService:
    def __init__(self, *, store: ReleaseReadinessStore | None = None) -> None:
        self._store = store or InMemoryReleaseReadinessStore()
        payload = self._store.load()
        self._scorecards: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("scorecards", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def generate_scorecard(
        self,
        *,
        tenant_id: str,
        scorecard_id: str,
        release_id: str,
        generated_by: str,
        ci_evidence: list[dict[str, Any]],
        gate_weights: dict[str, float] | None = None,
        minimum_pass_ratio: float = 0.85,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_scorecard_id = scorecard_id.strip().lower()
        if not normalized_scorecard_id:
            raise ValueError("scorecard_id must not be empty")

        normalized_release_id = release_id.strip()
        if not normalized_release_id:
            raise ValueError("release_id must not be empty")

        normalized_generated_by = generated_by.strip()
        if not normalized_generated_by:
            raise ValueError("generated_by must not be empty")

        if normalized_scorecard_id in self._scorecards:
            raise ValueError("scorecard already exists")

        normalized_evidence = self._normalize_evidence(ci_evidence)
        if not normalized_evidence:
            raise ValueError("ci_evidence must not be empty")

        weights = self._normalize_weights(gate_weights or {})
        if weights:
            for item in normalized_evidence:
                gate_name = str(item["gate_name"])
                if gate_name not in weights:
                    weights[gate_name] = 1.0
        else:
            weights = {str(item["gate_name"]): 1.0 for item in normalized_evidence}

        weighted_total = 0.0
        weighted_passed = 0.0
        critical_failure_count = 0
        blocked_reasons: list[str] = []

        gate_results: list[dict[str, Any]] = []
        for item in normalized_evidence:
            gate_name = str(item["gate_name"])
            status = str(item["status"])
            required = bool(item["required"])
            critical = bool(item["critical"])
            weight = float(weights.get(gate_name, 1.0))

            weighted_total += weight
            if status == "pass":
                weighted_passed += weight

            if critical and status != "pass":
                critical_failure_count += 1
                blocked_reasons.append(f"critical gate failed: {gate_name}")
            elif required and status == "fail":
                blocked_reasons.append(f"required gate failed: {gate_name}")

            gate_results.append(
                {
                    "gate_name": gate_name,
                    "status": status,
                    "required": required,
                    "critical": critical,
                    "weight": weight,
                    "details": dict(item.get("details", {})),
                    "recorded_at": float(item.get("recorded_at", time.time())),
                }
            )

        pass_ratio = 0.0 if weighted_total <= 0 else weighted_passed / weighted_total
        pass_ratio = round(pass_ratio, 6)
        release_blocked = critical_failure_count > 0 or any(
            "required gate failed" in reason for reason in blocked_reasons
        )

        if not release_blocked and pass_ratio < float(minimum_pass_ratio):
            release_blocked = True
            blocked_reasons.append(
                f"pass ratio {pass_ratio:.3f} below threshold {float(minimum_pass_ratio):.3f}"
            )

        if release_blocked:
            overall_status = "blocked"
        elif pass_ratio >= 0.97:
            overall_status = "ready"
        else:
            overall_status = "needs_review"

        score = round(pass_ratio * 100.0, 2)
        now = time.time()
        payload = {
            "scorecard_id": normalized_scorecard_id,
            "tenant_id": normalized_tenant,
            "release_id": normalized_release_id,
            "generated_by": normalized_generated_by,
            "score": score,
            "pass_ratio": pass_ratio,
            "minimum_pass_ratio": float(minimum_pass_ratio),
            "overall_status": overall_status,
            "release_blocked": release_blocked,
            "critical_failure_count": critical_failure_count,
            "blocked_reasons": blocked_reasons,
            "gate_results": gate_results,
            "created_at": now,
            "updated_at": now,
        }
        self._scorecards[normalized_scorecard_id] = payload
        self._trim_scorecards(limit=4000)
        self._persist()
        return dict(payload)

    def list_scorecards(
        self,
        *,
        tenant_id: str,
        release_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        normalized_release_id = release_id.strip() if release_id is not None else ""
        normalized_status = status.strip().lower() if status is not None else ""

        items = [
            dict(item)
            for item in self._scorecards.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        if normalized_release_id:
            items = [item for item in items if str(item.get("release_id", "")) == normalized_release_id]
        if normalized_status:
            items = [item for item in items if str(item.get("overall_status", "")).lower() == normalized_status]

        items.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return items[:limit]

    def get_scorecard(self, *, scorecard_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_scorecard_id = scorecard_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_scorecard_id:
            raise ValueError("scorecard_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._scorecards.get(normalized_scorecard_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    @staticmethod
    def _normalize_evidence(ci_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw in ci_evidence:
            if not isinstance(raw, dict):
                raise ValueError("ci_evidence entries must be objects")

            gate_name = str(raw.get("gate_name", "")).strip().lower()
            if not gate_name:
                raise ValueError("gate_name must not be empty")

            status = str(raw.get("status", "")).strip().lower()
            if status not in {"pass", "fail", "warn"}:
                raise ValueError("status must be pass|fail|warn")

            recorded_at_raw = raw.get("recorded_at")
            recorded_at = time.time() if recorded_at_raw is None else float(recorded_at_raw)

            details_raw = raw.get("details", {})
            if details_raw is None:
                details_raw = {}
            if not isinstance(details_raw, dict):
                raise ValueError("details must be an object")

            items.append(
                {
                    "gate_name": gate_name,
                    "status": status,
                    "required": bool(raw.get("required", True)),
                    "critical": bool(raw.get("critical", False)),
                    "details": {
                        str(key): str(value)
                        for key, value in details_raw.items()
                    },
                    "recorded_at": recorded_at,
                }
            )
        return items

    @staticmethod
    def _normalize_weights(gate_weights: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, value in gate_weights.items():
            gate_name = str(key).strip().lower()
            if not gate_name:
                continue
            weight = float(value)
            if weight <= 0:
                raise ValueError("gate_weights must be > 0")
            normalized[gate_name] = weight
        return normalized

    def _trim_scorecards(self, *, limit: int) -> None:
        if len(self._scorecards) <= limit:
            return

        items = sorted(
            self._scorecards.items(),
            key=lambda entry: float(entry[1].get("updated_at", 0.0)),
            reverse=True,
        )[:limit]
        self._scorecards = {key: dict(value) for key, value in items}

    def _persist(self) -> None:
        self._store.save({"scorecards": self._scorecards})
