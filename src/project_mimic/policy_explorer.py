"""Policy decision explorer with persisted evaluation trails."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4

from .policy import PolicyContext, PolicyEngine


class PolicyDecisionStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryPolicyDecisionStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {decision_id: dict(item) for decision_id, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {decision_id: dict(item) for decision_id, item in self._payload.items()}


class JsonFilePolicyDecisionStore:
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
        for decision_id, payload in loaded.items():
            if isinstance(decision_id, str) and isinstance(payload, dict):
                result[decision_id] = dict(payload)
        return result


class PolicyDecisionExplorer:
    def __init__(
        self,
        *,
        risk_threshold: float = 0.7,
        store: PolicyDecisionStore | None = None,
    ) -> None:
        self._store = store or InMemoryPolicyDecisionStore()
        self._items = self._store.load()
        self._engine = PolicyEngine(risk_threshold=risk_threshold)

    def evaluate(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        site_id: str,
        region_allowed: bool,
        has_authorization: bool,
        risk_score: float,
        action: str,
        jurisdiction: str = "global",
        metadata: dict[str, str] | None = None,
        simulate: bool = False,
    ) -> dict[str, Any]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not site_id.strip():
            raise ValueError("site_id must not be empty")
        if risk_score < 0.0 or risk_score > 1.0:
            raise ValueError("risk_score must be between 0 and 1")

        now = time.time()
        context = PolicyContext(
            actor_id=actor_id,
            site_id=site_id,
            region_allowed=region_allowed,
            has_authorization=has_authorization,
            risk_score=risk_score,
            action=action,
            jurisdiction=jurisdiction.strip() or "global",
            metadata=dict(metadata or {}),
        )
        decision = self._engine.evaluate(context, simulate=simulate)
        decision_id = f"policy_{uuid4().hex[:12]}"
        payload = {
            "decision_id": decision_id,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "site_id": site_id,
            "region_allowed": region_allowed,
            "has_authorization": has_authorization,
            "risk_score": float(risk_score),
            "action": action,
            "jurisdiction": context.jurisdiction,
            "metadata": dict(context.metadata),
            "simulate": bool(simulate),
            "allowed": bool(decision.allowed),
            "would_allow": decision.would_allow,
            "reason": decision.reason,
            "applied_rule_id": decision.applied_rule_id,
            "created_at": now,
            "explanations": [
                {
                    "rule_id": item.rule_id,
                    "priority": item.priority,
                    "verdict": item.verdict,
                    "reason": item.reason,
                }
                for item in decision.explanations
            ],
        }
        self._items[decision_id] = payload
        self._persist()
        return dict(payload)

    def list(
        self,
        *,
        tenant_id: str,
        allowed: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        items = [item for item in self._items.values() if str(item.get("tenant_id")) == tenant_id]
        if allowed is not None:
            items = [item for item in items if bool(item.get("allowed")) is allowed]
        items.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=True)
        return [dict(item) for item in items[:limit]]

    def get(self, *, decision_id: str) -> dict[str, Any]:
        item = self._items.get(decision_id)
        if item is None:
            raise KeyError(decision_id)
        return dict(item)

    def _persist(self) -> None:
        self._store.save(self._items)
