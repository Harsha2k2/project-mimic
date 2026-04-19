"""Consent and allowed-target governance controls."""

from __future__ import annotations

from fnmatch import fnmatchcase
import json
from pathlib import Path
import time
from typing import Any, Protocol


class GovernancePolicyStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryGovernancePolicyStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {tenant_id: dict(item) for tenant_id, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {tenant_id: dict(item) for tenant_id, item in self._payload.items()}


class JsonFileGovernancePolicyStore:
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
        for tenant_id, payload in loaded.items():
            if isinstance(tenant_id, str) and isinstance(payload, dict):
                result[tenant_id] = dict(payload)
        return result


class ConsentTargetGovernanceService:
    def __init__(self, *, store: GovernancePolicyStore | None = None) -> None:
        self._store = store or InMemoryGovernancePolicyStore()
        self._policies = self._store.load()

    def upsert_policy(
        self,
        *,
        tenant_id: str,
        consent_required: bool,
        allowed_target_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_patterns = sorted(
            {
                item.strip().lower()
                for item in (allowed_target_patterns or [])
                if item.strip()
            }
        )

        now = time.time()
        existing = self._policies.get(normalized_tenant)
        created_at = now if existing is None else float(existing.get("created_at", now))
        payload = {
            "tenant_id": normalized_tenant,
            "consent_required": bool(consent_required),
            "allowed_target_patterns": normalized_patterns,
            "created_at": created_at,
            "updated_at": now,
        }
        self._policies[normalized_tenant] = payload
        self._persist()
        return dict(payload)

    def get_policy(self, *, tenant_id: str) -> dict[str, Any]:
        payload = self._policies.get(tenant_id)
        if payload is None:
            raise KeyError(tenant_id)
        return dict(payload)

    def list_policies(self) -> list[dict[str, Any]]:
        return [dict(self._policies[key]) for key in sorted(self._policies.keys())]

    def evaluate(
        self,
        *,
        tenant_id: str,
        action_type: str,
        target: str | None,
        consent_granted: bool,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_action_type = action_type.strip().lower()
        if not normalized_action_type:
            raise ValueError("action_type must not be empty")

        normalized_target = (target or "").strip().lower()
        now = time.time()

        policy = self._policies.get(normalized_tenant)
        if policy is None:
            return {
                "tenant_id": normalized_tenant,
                "action_type": normalized_action_type,
                "target": normalized_target or None,
                "consent_granted": bool(consent_granted),
                "allowed": True,
                "reason": "no_governance_policy",
                "matched_pattern": None,
                "allowed_target_patterns": [],
                "evaluated_at": now,
            }

        allowed_target_patterns = [str(item) for item in policy.get("allowed_target_patterns", [])]
        requires_consent = bool(policy.get("consent_required", False))
        if requires_consent and not bool(consent_granted):
            return {
                "tenant_id": normalized_tenant,
                "action_type": normalized_action_type,
                "target": normalized_target or None,
                "consent_granted": False,
                "allowed": False,
                "reason": "consent_required",
                "matched_pattern": None,
                "allowed_target_patterns": allowed_target_patterns,
                "evaluated_at": now,
            }

        if normalized_action_type in {"click", "type"} and allowed_target_patterns:
            if not normalized_target:
                return {
                    "tenant_id": normalized_tenant,
                    "action_type": normalized_action_type,
                    "target": None,
                    "consent_granted": bool(consent_granted),
                    "allowed": False,
                    "reason": "target_required",
                    "matched_pattern": None,
                    "allowed_target_patterns": allowed_target_patterns,
                    "evaluated_at": now,
                }

            for pattern in allowed_target_patterns:
                if fnmatchcase(normalized_target, pattern):
                    return {
                        "tenant_id": normalized_tenant,
                        "action_type": normalized_action_type,
                        "target": normalized_target,
                        "consent_granted": bool(consent_granted),
                        "allowed": True,
                        "reason": "target_allowlisted",
                        "matched_pattern": pattern,
                        "allowed_target_patterns": allowed_target_patterns,
                        "evaluated_at": now,
                    }

            return {
                "tenant_id": normalized_tenant,
                "action_type": normalized_action_type,
                "target": normalized_target,
                "consent_granted": bool(consent_granted),
                "allowed": False,
                "reason": "target_not_allowlisted",
                "matched_pattern": None,
                "allowed_target_patterns": allowed_target_patterns,
                "evaluated_at": now,
            }

        return {
            "tenant_id": normalized_tenant,
            "action_type": normalized_action_type,
            "target": normalized_target or None,
            "consent_granted": bool(consent_granted),
            "allowed": True,
            "reason": "policy_pass",
            "matched_pattern": None,
            "allowed_target_patterns": allowed_target_patterns,
            "evaluated_at": now,
        }

    def _persist(self) -> None:
        self._store.save(self._policies)
