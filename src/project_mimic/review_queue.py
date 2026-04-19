"""Human-in-the-loop review queue for low-confidence actions."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class ReviewQueueStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryReviewQueueStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {review_id: dict(item) for review_id, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {review_id: dict(item) for review_id, item in self._payload.items()}


class JsonFileReviewQueueStore:
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
        for review_id, payload in loaded.items():
            if isinstance(review_id, str) and isinstance(payload, dict):
                result[review_id] = dict(payload)
        return result


class HumanReviewQueue:
    def __init__(self, *, store: ReviewQueueStore | None = None) -> None:
        self._store = store or InMemoryReviewQueueStore()
        self._items = self._store.load()

    def submit(
        self,
        *,
        tenant_id: str,
        action_payload: dict[str, Any],
        confidence: float,
        reason: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if not reason.strip():
            raise ValueError("reason must not be empty")
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between 0 and 1")

        review_id = f"review_{uuid4().hex[:12]}"
        now = time.time()
        payload = {
            "review_id": review_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "action_payload": dict(action_payload),
            "confidence": float(confidence),
            "reason": reason,
            "status": "pending",
            "resolution": None,
            "resolution_note": None,
            "created_at": now,
            "resolved_at": None,
        }
        self._items[review_id] = payload
        self._persist()
        return dict(payload)

    def list(self, *, tenant_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        items = [item for item in self._items.values() if str(item.get("tenant_id")) == tenant_id]
        if status is not None:
            normalized = status.strip().lower()
            items = [item for item in items if str(item.get("status", "")).lower() == normalized]

        items.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=True)
        return [dict(item) for item in items[:limit]]

    def resolve(self, *, review_id: str, decision: str, note: str | None = None) -> dict[str, Any]:
        item = self._items.get(review_id)
        if item is None:
            raise KeyError(review_id)

        if item.get("status") != "pending":
            raise ValueError("review item is already resolved")

        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")

        item["status"] = normalized_decision
        item["resolution"] = normalized_decision
        item["resolution_note"] = note
        item["resolved_at"] = time.time()
        self._persist()
        return dict(item)

    def _persist(self) -> None:
        self._store.save(self._items)
