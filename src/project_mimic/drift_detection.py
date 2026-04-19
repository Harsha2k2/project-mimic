"""Online drift monitor for model and grounding metrics."""

from __future__ import annotations

from collections import deque
import time
from typing import Any


class DriftMonitor:
    def __init__(
        self,
        *,
        baseline_window: int = 20,
        recent_window: int = 10,
        default_threshold: float = 0.25,
    ) -> None:
        if baseline_window <= 0:
            raise ValueError("baseline_window must be positive")
        if recent_window <= 0:
            raise ValueError("recent_window must be positive")
        if default_threshold <= 0:
            raise ValueError("default_threshold must be positive")

        self._baseline_window = baseline_window
        self._recent_window = recent_window
        self._default_threshold = default_threshold
        self._series: dict[str, dict[str, Any]] = {}

    def ingest(
        self,
        *,
        stream_id: str,
        metric_name: str,
        value: float,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        if not stream_id.strip():
            raise ValueError("stream_id must not be empty")
        if not metric_name.strip():
            raise ValueError("metric_name must not be empty")

        key = self._series_key(stream_id, metric_name)
        state = self._series.get(key)
        if state is None:
            state = {
                "stream_id": stream_id.strip(),
                "metric_name": metric_name.strip(),
                "baseline_mean": 0.0,
                "baseline_samples": 0,
                "recent": deque(maxlen=self._recent_window),
                "drift_score": 0.0,
                "threshold": threshold if threshold is not None else self._default_threshold,
                "alert_active": False,
                "updated_at": 0.0,
            }
            self._series[key] = state

        if threshold is not None:
            if threshold <= 0:
                raise ValueError("threshold must be positive")
            state["threshold"] = threshold

        value_float = float(value)
        baseline_samples = int(state["baseline_samples"])
        baseline_mean = float(state["baseline_mean"])

        if baseline_samples < self._baseline_window:
            next_samples = baseline_samples + 1
            next_baseline = ((baseline_mean * baseline_samples) + value_float) / next_samples
            state["baseline_samples"] = next_samples
            state["baseline_mean"] = next_baseline
            state["drift_score"] = 0.0
            state["alert_active"] = False
        else:
            recent = state["recent"]
            recent.append(value_float)
            recent_mean = sum(recent) / len(recent)
            denominator = max(abs(float(state["baseline_mean"])), 1e-6)
            drift_score = abs(recent_mean - float(state["baseline_mean"])) / denominator
            state["drift_score"] = drift_score
            state["alert_active"] = drift_score >= float(state["threshold"])

        state["updated_at"] = time.time()
        return self._status_from_state(state)

    def status(self, *, stream_id: str, metric_name: str) -> dict[str, Any] | None:
        key = self._series_key(stream_id, metric_name)
        state = self._series.get(key)
        if state is None:
            return None
        return self._status_from_state(state)

    def active_alerts(self) -> list[dict[str, Any]]:
        alerts = [
            self._status_from_state(state)
            for state in self._series.values()
            if bool(state.get("alert_active", False))
        ]
        alerts.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return alerts

    @staticmethod
    def _series_key(stream_id: str, metric_name: str) -> str:
        return f"{stream_id.strip()}::{metric_name.strip()}"

    @staticmethod
    def _status_from_state(state: dict[str, Any]) -> dict[str, Any]:
        recent = state.get("recent")
        recent_values = list(recent) if isinstance(recent, deque) else []
        recent_mean = sum(recent_values) / len(recent_values) if recent_values else None
        return {
            "stream_id": state["stream_id"],
            "metric_name": state["metric_name"],
            "baseline_mean": float(state["baseline_mean"]),
            "baseline_samples": int(state["baseline_samples"]),
            "recent_mean": recent_mean,
            "recent_sample_count": len(recent_values),
            "drift_score": float(state["drift_score"]),
            "threshold": float(state["threshold"]),
            "alert_active": bool(state["alert_active"]),
            "updated_at": float(state["updated_at"]),
        }
