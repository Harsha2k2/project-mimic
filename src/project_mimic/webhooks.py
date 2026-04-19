"""Webhook subscription storage and lifecycle event publishing."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4

import httpx


class WebhookSubscriptionStore(Protocol):
    def save(self, subscriptions: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryWebhookSubscriptionStore:
    def __init__(self) -> None:
        self._subscriptions: dict[str, dict[str, Any]] = {}

    def save(self, subscriptions: dict[str, dict[str, Any]]) -> None:
        self._subscriptions = {
            subscription_id: dict(payload)
            for subscription_id, payload in subscriptions.items()
        }

    def load(self) -> dict[str, dict[str, Any]]:
        return {
            subscription_id: dict(payload)
            for subscription_id, payload in self._subscriptions.items()
        }


class JsonFileWebhookSubscriptionStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, subscriptions: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(subscriptions, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}

        subscriptions: dict[str, dict[str, Any]] = {}
        for subscription_id, payload in loaded.items():
            if isinstance(subscription_id, str) and isinstance(payload, dict):
                subscriptions[subscription_id] = dict(payload)
        return subscriptions


class LifecycleEventWebhookPublisher:
    def __init__(
        self,
        *,
        store: WebhookSubscriptionStore | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._store = store or InMemoryWebhookSubscriptionStore()
        self._timeout_seconds = timeout_seconds
        self._subscriptions = self._store.load()

    def create_subscription(
        self,
        *,
        name: str,
        callback_url: str,
        events: list[str],
        tenant_id: str,
        secret: str | None = None,
    ) -> dict[str, Any]:
        cleaned_name = name.strip()
        cleaned_url = callback_url.strip()
        if not cleaned_name:
            raise ValueError("name must not be empty")
        if not cleaned_url:
            raise ValueError("callback_url must not be empty")

        normalized_events = sorted({event.strip() for event in events if event.strip()})
        now = time.time()
        subscription_id = f"sub_{uuid4().hex[:12]}"
        payload = {
            "subscription_id": subscription_id,
            "name": cleaned_name,
            "callback_url": cleaned_url,
            "events": normalized_events,
            "tenant_id": tenant_id,
            "secret": secret.strip() if secret else None,
            "active": True,
            "created_at": now,
            "updated_at": now,
        }
        self._subscriptions[subscription_id] = payload
        self._persist()
        return dict(payload)

    def list_subscriptions(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        items = list(self._subscriptions.values())
        if tenant_id is not None:
            items = [item for item in items if item.get("tenant_id") == tenant_id]
        items.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=False)
        return [dict(item) for item in items]

    def emit(self, *, event_type: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, int]:
        envelope = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": time.time(),
            "payload": payload,
        }

        delivered = 0
        failed = 0

        for subscription in self._subscriptions.values():
            if not bool(subscription.get("active", True)):
                continue
            if str(subscription.get("tenant_id", "")) != tenant_id:
                continue

            events = subscription.get("events", [])
            if isinstance(events, list) and events:
                normalized_events = [str(item) for item in events]
                if event_type not in normalized_events and "*" not in normalized_events:
                    continue

            headers = {
                "Content-Type": "application/json",
                "X-Project-Mimic-Event": event_type,
                "X-Project-Mimic-Subscription": str(subscription.get("subscription_id", "")),
            }
            secret = subscription.get("secret")
            if isinstance(secret, str) and secret:
                headers["X-Project-Mimic-Webhook-Secret"] = secret

            try:
                response = httpx.post(
                    str(subscription.get("callback_url", "")),
                    json=envelope,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                delivered += 1
            except Exception:
                failed += 1

        return {"delivered": delivered, "failed": failed}

    def _persist(self) -> None:
        self._store.save(self._subscriptions)
