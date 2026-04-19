"""In-memory event broker and cursor-based stream helpers."""

from __future__ import annotations

from collections import deque
from threading import Condition
import time
from typing import Any
from uuid import uuid4


class EventStreamBroker:
    def __init__(self, *, max_events: int = 1000) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._condition = Condition()
        self._next_sequence = 0

    def publish(self, *, event_type: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            self._next_sequence += 1
            event = {
                "sequence": self._next_sequence,
                "event_id": str(uuid4()),
                "event_type": event_type,
                "tenant_id": tenant_id,
                "timestamp": time.time(),
                "payload": payload,
            }
            self._events.append(event)
            self._condition.notify_all()
            return dict(event)

    def list_events(
        self,
        *,
        after_id: int,
        tenant_id: str,
        max_events: int,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if max_events <= 0:
            return []

        with self._condition:
            filtered: list[dict[str, Any]] = []
            for event in self._events:
                sequence = int(event.get("sequence", 0))
                if sequence <= after_id:
                    continue
                if str(event.get("tenant_id", "")) != tenant_id:
                    continue
                if event_type and str(event.get("event_type", "")) != event_type:
                    continue
                filtered.append(dict(event))
                if len(filtered) >= max_events:
                    break
            return filtered

    def wait_for_new_events(self, *, after_id: int, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            return self.latest_sequence() > after_id

        deadline = time.time() + timeout_seconds
        with self._condition:
            while self._next_sequence <= after_id:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def latest_sequence(self) -> int:
        with self._condition:
            return self._next_sequence
