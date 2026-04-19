"""Synthetic monitoring probes for API, queue, worker, and inference paths."""

from __future__ import annotations

import time
from typing import Any, Callable

from .queue_runtime import InMemoryActionQueue
from .vision.triton_client import TritonConfig, TritonVisionClient


class SyntheticMonitoringError(RuntimeError):
    """Raised when synthetic monitoring cannot execute probes."""


class SyntheticMonitor:
    def __init__(
        self,
        *,
        api_probe: Callable[[], None] | None = None,
        worker_probe: Callable[[], None] | None = None,
        queue: InMemoryActionQueue | None = None,
        triton_client: TritonVisionClient | None = None,
        triton_endpoint: str = "",
        triton_model_name: str = "ui-detector",
    ) -> None:
        self._api_probe = api_probe
        self._worker_probe = worker_probe
        self._queue = queue
        self._triton_client = triton_client
        self._triton_endpoint = triton_endpoint.strip()
        self._triton_model_name = triton_model_name.strip() or "ui-detector"

    def run_all(self) -> dict[str, Any]:
        checks = {
            "api": self._run_probe("api", self._api_probe),
            "queue": self._run_queue_probe(),
            "worker": self._run_probe("worker", self._worker_probe),
            "inference": self._run_inference_probe(),
        }
        overall_healthy = all(bool(result.get("ok", False)) for result in checks.values())
        return {
            "timestamp": time.time(),
            "overall_healthy": overall_healthy,
            "checks": checks,
        }

    def _run_probe(self, name: str, probe: Callable[[], None] | None) -> dict[str, Any]:
        started = time.perf_counter()
        if probe is None:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "name": name,
                "ok": False,
                "latency_ms": round(elapsed_ms, 4),
                "message": f"{name} probe is not configured",
            }

        try:
            probe()
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "name": name,
                "ok": False,
                "latency_ms": round(elapsed_ms, 4),
                "message": str(exc),
            }

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "name": name,
            "ok": True,
            "latency_ms": round(elapsed_ms, 4),
            "message": "ok",
        }

    def _run_queue_probe(self) -> dict[str, Any]:
        started = time.perf_counter()
        if self._queue is None:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "name": "queue",
                "ok": False,
                "latency_ms": round(elapsed_ms, 4),
                "message": "queue probe is not configured",
            }

        try:
            depth = self._queue.queue_depth()
            dead_letter = len(self._queue.list_dead_letter())
            self._queue.requeue_expired_leases()
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "name": "queue",
                "ok": False,
                "latency_ms": round(elapsed_ms, 4),
                "message": str(exc),
            }

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "name": "queue",
            "ok": True,
            "latency_ms": round(elapsed_ms, 4),
            "message": "ok",
            "queue_depth": int(depth),
            "dead_letter": int(dead_letter),
        }

    def _run_inference_probe(self) -> dict[str, Any]:
        started = time.perf_counter()

        try:
            client = self._resolve_triton_client()
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "name": "inference",
                "ok": False,
                "latency_ms": round(elapsed_ms, 4),
                "message": str(exc),
            }

        try:
            entities = client.infer_entities(b"synthetic-monitor")
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "name": "inference",
                "ok": False,
                "latency_ms": round(elapsed_ms, 4),
                "message": str(exc),
            }

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "name": "inference",
            "ok": True,
            "latency_ms": round(elapsed_ms, 4),
            "message": "ok",
            "entities": len(entities),
        }

    def _resolve_triton_client(self) -> TritonVisionClient:
        if self._triton_client is not None:
            return self._triton_client

        if not self._triton_endpoint:
            raise SyntheticMonitoringError("inference probe is not configured")

        return TritonVisionClient(
            TritonConfig(
                endpoint=self._triton_endpoint,
                model_name=self._triton_model_name,
                allowed_hosts=("127.0.0.1", "localhost"),
            )
        )
