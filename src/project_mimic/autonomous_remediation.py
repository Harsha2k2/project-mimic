"""Autonomous remediation execution for known failure signatures."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable, Protocol
from uuid import uuid4


class AutonomousRemediationStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryAutonomousRemediationStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileAutonomousRemediationStore:
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


RemediationActionExecutor = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]


class AutonomousRemediationService:
    def __init__(
        self,
        *,
        store: AutonomousRemediationStore | None = None,
        action_executor: RemediationActionExecutor | None = None,
    ) -> None:
        self._store = store or InMemoryAutonomousRemediationStore()
        self._action_executor = action_executor

        payload = self._store.load()
        self._signatures: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("signatures", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._executions: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("executions", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_signature(
        self,
        *,
        signature_id: str,
        tenant_id: str,
        incident_class: str,
        failure_code: str | None,
        threshold: float,
        cooldown_seconds: int,
        enabled: bool,
        action_plan: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_signature_id = signature_id.strip().lower()
        if not normalized_signature_id:
            raise ValueError("signature_id must not be empty")

        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_incident_class = incident_class.strip().lower()
        if not normalized_incident_class:
            raise ValueError("incident_class must not be empty")

        normalized_failure_code = None
        if failure_code is not None:
            cleaned_failure_code = failure_code.strip().lower()
            normalized_failure_code = cleaned_failure_code or None

        validated_threshold = self._validated_non_negative_float(threshold, "threshold")
        validated_cooldown = self._validated_non_negative_int(cooldown_seconds, "cooldown_seconds")
        normalized_action_plan = self._normalize_action_plan(action_plan)

        now = time.time()
        existing = self._signatures.get(normalized_signature_id)
        created_at = now if existing is None else float(existing.get("created_at", now))
        last_triggered_at = None if existing is None else existing.get("last_triggered_at")

        payload = {
            "signature_id": normalized_signature_id,
            "tenant_id": normalized_tenant,
            "incident_class": normalized_incident_class,
            "failure_code": normalized_failure_code,
            "threshold": validated_threshold,
            "cooldown_seconds": validated_cooldown,
            "enabled": bool(enabled),
            "action_plan": normalized_action_plan,
            "last_triggered_at": last_triggered_at,
            "created_at": created_at,
            "updated_at": now,
        }
        self._signatures[normalized_signature_id] = payload
        self._persist()
        return dict(payload)

    def get_signature(self, *, signature_id: str, tenant_id: str) -> dict[str, Any]:
        signature = self._get_signature_for_tenant(signature_id=signature_id, tenant_id=tenant_id)
        return dict(signature)

    def list_signatures(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        normalized_tenant = None if tenant_id is None else tenant_id.strip()
        items: list[dict[str, Any]] = []
        for signature_key in sorted(self._signatures.keys()):
            item = self._signatures[signature_key]
            if normalized_tenant and str(item.get("tenant_id", "")) != normalized_tenant:
                continue
            items.append(dict(item))
        return items

    def trigger(
        self,
        *,
        signature_id: str,
        tenant_id: str,
        observed_value: float,
        signal_label: str,
        execute: bool,
        initiated_by: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signature = self._get_signature_for_tenant(signature_id=signature_id, tenant_id=tenant_id)
        validated_observed_value = self._validated_non_negative_float(observed_value, "observed_value")

        normalized_signal_label = signal_label.strip().lower()
        if not normalized_signal_label:
            raise ValueError("signal_label must not be empty")

        normalized_initiator = initiated_by.strip() or "autonomous-remediation"
        threshold = float(signature.get("threshold", 0.0))

        now = time.time()
        reason = "below_threshold"
        matched = False
        executed = False
        action_results: list[dict[str, Any]] = []

        if not bool(signature.get("enabled", False)):
            reason = "signature_disabled"
        elif validated_observed_value < threshold:
            reason = "below_threshold"
        elif self._cooldown_active(signature=signature, now=now):
            reason = "cooldown_active"
        else:
            matched = True
            signature["last_triggered_at"] = now
            signature["updated_at"] = now

            if not execute:
                reason = "dry_run"
            else:
                reason = "actions_executed"
                executed = True
                action_results = self._execute_action_plan(
                    signature=signature,
                    context=context or {},
                )
                if not action_results:
                    reason = "no_actions_configured"
                elif any(not bool(item.get("success", False)) for item in action_results):
                    reason = "actions_partially_failed"

        execution_id = f"remed_{uuid4().hex[:12]}"
        execution = {
            "execution_id": execution_id,
            "signature_id": str(signature.get("signature_id", "")),
            "tenant_id": str(signature.get("tenant_id", "")),
            "incident_class": str(signature.get("incident_class", "")),
            "failure_code": signature.get("failure_code"),
            "observed_value": validated_observed_value,
            "threshold": threshold,
            "matched": matched,
            "executed": executed,
            "reason": reason,
            "initiated_by": normalized_initiator,
            "signal_label": normalized_signal_label,
            "action_results": action_results,
            "context": dict(context or {}),
            "created_at": now,
        }

        self._executions[execution_id] = execution
        self._trim_execution_history(limit=2000)
        self._persist()
        return dict(execution)

    def get_execution(self, *, execution_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_execution_id = execution_id.strip()
        normalized_tenant = tenant_id.strip()
        if not normalized_execution_id or not normalized_tenant:
            raise ValueError("execution_id and tenant_id must not be empty")

        payload = self._executions.get(normalized_execution_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def list_executions(
        self,
        *,
        tenant_id: str,
        signature_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        if limit <= 0:
            return []

        normalized_signature_id = None if signature_id is None else signature_id.strip().lower()
        items = [
            dict(payload)
            for payload in self._executions.values()
            if str(payload.get("tenant_id", "")) == normalized_tenant
            and (
                normalized_signature_id is None
                or str(payload.get("signature_id", "")) == normalized_signature_id
            )
        ]
        items.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=True)
        return items[:limit]

    def _execute_action_plan(
        self,
        *,
        signature: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        action_plan = signature.get("action_plan", [])
        if not isinstance(action_plan, list):
            return []

        results: list[dict[str, Any]] = []
        for action in action_plan:
            if not isinstance(action, dict):
                continue

            action_type = str(action.get("action_type", "")).strip().lower()
            if not action_type:
                continue

            parameters_raw = action.get("parameters", {})
            parameters = dict(parameters_raw) if isinstance(parameters_raw, dict) else {}
            results.append(
                self._execute_single_action(
                    action_type=action_type,
                    parameters=parameters,
                    context=context,
                    signature=signature,
                )
            )
        return results

    def _execute_single_action(
        self,
        *,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        signature: dict[str, Any],
    ) -> dict[str, Any]:
        executor = self._action_executor
        if executor is None:
            return {
                "action_type": action_type,
                "success": False,
                "status": "failed",
                "details": {"error": "no action executor configured"},
            }

        try:
            result = executor(
                action_type,
                dict(parameters),
                {
                    "signature_id": str(signature.get("signature_id", "")),
                    "tenant_id": str(signature.get("tenant_id", "")),
                    "incident_class": str(signature.get("incident_class", "")),
                    "context": dict(context),
                },
            )
        except Exception as exc:
            return {
                "action_type": action_type,
                "success": False,
                "status": "failed",
                "details": {"error": str(exc)},
            }

        if not isinstance(result, dict):
            return {
                "action_type": action_type,
                "success": True,
                "status": "succeeded",
                "details": {"result": result},
            }

        success = bool(result.get("success", True))
        status = str(result.get("status", "succeeded" if success else "failed"))
        details_raw = result.get("details", {})
        details = dict(details_raw) if isinstance(details_raw, dict) else {"result": details_raw}
        return {
            "action_type": action_type,
            "success": success,
            "status": status,
            "details": details,
        }

    def _cooldown_active(self, *, signature: dict[str, Any], now: float) -> bool:
        cooldown = int(signature.get("cooldown_seconds", 0))
        if cooldown <= 0:
            return False

        last_triggered_at = signature.get("last_triggered_at")
        if last_triggered_at is None:
            return False

        elapsed = now - float(last_triggered_at)
        return elapsed < cooldown

    def _get_signature_for_tenant(self, *, signature_id: str, tenant_id: str) -> dict[str, Any]:
        normalized_signature_id = signature_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_signature_id:
            raise ValueError("signature_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        signature = self._signatures.get(normalized_signature_id)
        if signature is None:
            raise ValueError("signature not found")
        if str(signature.get("tenant_id", "")) != normalized_tenant:
            raise ValueError("signature does not belong to tenant")
        return signature

    def _normalize_action_plan(self, action_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not action_plan:
            raise ValueError("action_plan must include at least one action")

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(action_plan):
            if not isinstance(item, dict):
                raise ValueError(f"action_plan[{index}] must be an object")

            action_type = str(item.get("action_type", "")).strip().lower()
            if not action_type:
                raise ValueError(f"action_plan[{index}].action_type must not be empty")

            parameters = item.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError(f"action_plan[{index}].parameters must be an object")

            normalized.append(
                {
                    "action_type": action_type,
                    "parameters": dict(parameters),
                }
            )
        return normalized

    @staticmethod
    def _validated_non_negative_int(value: int, field_name: str) -> int:
        numeric = int(value)
        if numeric < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return numeric

    @staticmethod
    def _validated_non_negative_float(value: float, field_name: str) -> float:
        numeric = float(value)
        if numeric < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return numeric

    def _trim_execution_history(self, *, limit: int) -> None:
        if len(self._executions) <= limit:
            return

        execution_ids = sorted(
            self._executions.keys(),
            key=lambda key: float(self._executions[key].get("created_at", 0.0)),
            reverse=True,
        )
        keep = set(execution_ids[:limit])
        self._executions = {
            key: value
            for key, value in self._executions.items()
            if key in keep
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "signatures": self._signatures,
                "executions": self._executions,
            }
        )
