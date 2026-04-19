"""Governance approval workflows for high-risk policy changes."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol


class GovernanceApprovalStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryGovernanceApprovalStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileGovernanceApprovalStore:
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


class GovernanceApprovalWorkflowService:
    def __init__(self, *, store: GovernanceApprovalStore | None = None) -> None:
        self._store = store or InMemoryGovernanceApprovalStore()
        payload = self._store.load()
        self._requests: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("requests", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def submit_request(
        self,
        *,
        tenant_id: str,
        request_id: str,
        policy_id: str,
        change_summary: str,
        risk_score: float,
        submitted_by: str,
        required_approvals: int = 2,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_request_id = request_id.strip().lower()
        if not normalized_request_id:
            raise ValueError("request_id must not be empty")
        if normalized_request_id in self._requests:
            raise ValueError("approval request already exists")

        normalized_policy_id = policy_id.strip().lower()
        if not normalized_policy_id:
            raise ValueError("policy_id must not be empty")

        normalized_change_summary = change_summary.strip()
        if not normalized_change_summary:
            raise ValueError("change_summary must not be empty")

        validated_risk_score = float(risk_score)
        if validated_risk_score < 0.0 or validated_risk_score > 1.0:
            raise ValueError("risk_score must be within [0, 1]")
        if validated_risk_score < 0.7:
            raise ValueError("approval workflow requires high-risk change (risk_score >= 0.7)")

        normalized_submitted_by = submitted_by.strip()
        if not normalized_submitted_by:
            raise ValueError("submitted_by must not be empty")

        validated_required_approvals = int(required_approvals)
        if validated_required_approvals <= 0:
            raise ValueError("required_approvals must be > 0")

        now = time.time()
        payload = {
            "request_id": normalized_request_id,
            "tenant_id": normalized_tenant,
            "policy_id": normalized_policy_id,
            "change_summary": normalized_change_summary,
            "risk_score": validated_risk_score,
            "submitted_by": normalized_submitted_by,
            "required_approvals": validated_required_approvals,
            "approvals": [],
            "rejections": [],
            "status": "pending",
            "metadata": {
                str(key): str(value)
                for key, value in dict(metadata or {}).items()
            },
            "created_at": now,
            "updated_at": now,
        }
        self._requests[normalized_request_id] = payload
        self._persist()
        return dict(payload)

    def approve_request(
        self,
        *,
        tenant_id: str,
        request_id: str,
        approver: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        payload = self._get_owned_request(tenant_id=tenant_id, request_id=request_id)
        if str(payload.get("status", "")) != "pending":
            raise ValueError("approval request is not pending")

        normalized_approver = approver.strip()
        if not normalized_approver:
            raise ValueError("approver must not be empty")
        if normalized_approver == str(payload.get("submitted_by", "")):
            raise ValueError("submitter cannot approve own request")

        existing_approvers = {
            str(item.get("actor", ""))
            for item in payload.get("approvals", [])
            if isinstance(item, dict)
        }
        if normalized_approver in existing_approvers:
            raise ValueError("approver already recorded")

        rejection_actors = {
            str(item.get("actor", ""))
            for item in payload.get("rejections", [])
            if isinstance(item, dict)
        }
        if normalized_approver in rejection_actors:
            raise ValueError("actor already rejected this request")

        approval_event = {
            "actor": normalized_approver,
            "comment": "" if comment is None else str(comment).strip(),
            "timestamp": time.time(),
        }
        approvals = [dict(item) for item in payload.get("approvals", []) if isinstance(item, dict)]
        approvals.append(approval_event)
        payload["approvals"] = approvals

        if len(approvals) >= int(payload.get("required_approvals", 1)):
            payload["status"] = "approved"

        payload["updated_at"] = time.time()
        self._requests[str(payload["request_id"])] = payload
        self._persist()
        return dict(payload)

    def reject_request(
        self,
        *,
        tenant_id: str,
        request_id: str,
        approver: str,
        reason: str,
    ) -> dict[str, Any]:
        payload = self._get_owned_request(tenant_id=tenant_id, request_id=request_id)
        if str(payload.get("status", "")) != "pending":
            raise ValueError("approval request is not pending")

        normalized_approver = approver.strip()
        if not normalized_approver:
            raise ValueError("approver must not be empty")
        if normalized_approver == str(payload.get("submitted_by", "")):
            raise ValueError("submitter cannot reject own request")

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason must not be empty")

        approval_actors = {
            str(item.get("actor", ""))
            for item in payload.get("approvals", [])
            if isinstance(item, dict)
        }
        if normalized_approver in approval_actors:
            raise ValueError("actor already approved this request")

        rejection_actors = {
            str(item.get("actor", ""))
            for item in payload.get("rejections", [])
            if isinstance(item, dict)
        }
        if normalized_approver in rejection_actors:
            raise ValueError("approver already rejected")

        rejection_event = {
            "actor": normalized_approver,
            "reason": normalized_reason,
            "timestamp": time.time(),
        }
        rejections = [dict(item) for item in payload.get("rejections", []) if isinstance(item, dict)]
        rejections.append(rejection_event)
        payload["rejections"] = rejections
        payload["status"] = "rejected"
        payload["updated_at"] = time.time()

        self._requests[str(payload["request_id"])] = payload
        self._persist()
        return dict(payload)

    def get_request(self, *, tenant_id: str, request_id: str) -> dict[str, Any] | None:
        normalized_request_id = request_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_request_id:
            raise ValueError("request_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._requests.get(normalized_request_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def list_requests(
        self,
        *,
        tenant_id: str,
        policy_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        normalized_policy = policy_id.strip().lower() if policy_id is not None else ""
        normalized_status = status.strip().lower() if status is not None else ""
        if normalized_status and normalized_status not in {"pending", "approved", "rejected"}:
            raise ValueError("status must be pending|approved|rejected")

        items = [
            dict(item)
            for item in self._requests.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        if normalized_policy:
            items = [item for item in items if str(item.get("policy_id", "")) == normalized_policy]
        if normalized_status:
            items = [item for item in items if str(item.get("status", "")).lower() == normalized_status]

        items.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return items[:limit]

    def _get_owned_request(self, *, tenant_id: str, request_id: str) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        normalized_request_id = request_id.strip().lower()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_request_id:
            raise ValueError("request_id must not be empty")

        payload = self._requests.get(normalized_request_id)
        if payload is None:
            raise ValueError("approval request not found")
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            raise ValueError("approval request does not belong to tenant")
        return dict(payload)

    def _persist(self) -> None:
        self._store.save({"requests": self._requests})
