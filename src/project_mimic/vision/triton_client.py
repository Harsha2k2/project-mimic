"""Triton HTTP client adapter for vision inference."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import time
from typing import Any

import httpx

from .grounding import BBox, UIEntity
from .pipeline import (
    VisionTemporalCache,
    apply_role_thresholds,
    deduplicate_entities,
    normalize_ocr_text,
)
from ..reliability import (
    BackoffPolicy,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    TransientDependencyError,
    retry_with_backoff,
)


class TritonInferenceError(RuntimeError):
    """Raised when Triton inference fails or returns invalid payloads."""


@dataclass(frozen=True)
class TritonConfig:
    endpoint: str
    model_name: str
    timeout_s: float = 5.0


class TritonVisionClient:
    """Small HTTP adapter for Triton infer endpoint."""

    def __init__(
        self,
        config: TritonConfig,
        client: httpx.Client | None = None,
        *,
        circuit_breaker: CircuitBreaker | None = None,
        backoff_policy: BackoffPolicy | None = None,
        sleep_fn=time.sleep,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout_s)
        self._cache = VisionTemporalCache()
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=8.0)
        )
        self._backoff_policy = backoff_policy or BackoffPolicy(
            base_delay_ms=75,
            max_delay_ms=500,
            jitter_ratio=0.15,
            max_attempts=3,
        )
        self._sleep = sleep_fn

    def infer(self, screenshot: bytes, task_hint: str = "") -> dict[str, Any]:
        payload = _build_payload(screenshot=screenshot, task_hint=task_hint)
        url = f"{self.config.endpoint}/v2/models/{self.config.model_name}/infer"

        def _request_once() -> dict[str, Any]:
            if not self._circuit_breaker.allow_request():
                raise CircuitOpenError("triton circuit open")

            try:
                response = self._client.post(url, json=payload)
            except Exception as exc:
                self._circuit_breaker.record_failure()
                raise TransientDependencyError("triton transport failure") from exc

            if response.status_code >= 500:
                self._circuit_breaker.record_failure()
                raise TransientDependencyError(f"triton transient error status={response.status_code}")
            if response.status_code >= 400:
                self._circuit_breaker.record_failure()
                raise TritonInferenceError(f"triton error status={response.status_code}")

            try:
                data = response.json()
            except ValueError as exc:
                self._circuit_breaker.record_failure()
                raise TritonInferenceError("triton returned non-json response") from exc

            if "entities" not in data:
                self._circuit_breaker.record_failure()
                raise TritonInferenceError("triton response missing entities")

            self._circuit_breaker.record_success()
            return data

        try:
            return retry_with_backoff(
                _request_once,
                policy=self._backoff_policy,
                is_transient=lambda exc: isinstance(exc, (TransientDependencyError, CircuitOpenError)),
                on_retry=lambda _attempt, delay_ms, _err: self._sleep(delay_ms / 1000.0),
            )
        except (TransientDependencyError, CircuitOpenError) as exc:
            raise TritonInferenceError(str(exc)) from exc

    def infer_entities(
        self,
        screenshot: bytes,
        task_hint: str = "",
        locale: str = "en_US",
        role_thresholds: dict[str, float] | None = None,
    ) -> list[UIEntity]:
        cache_key = self._cache.make_key(screenshot)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        raw = self.infer(screenshot=screenshot, task_hint=task_hint)
        entities = []
        for item in raw.get("entities", []):
            normalized_text = normalize_ocr_text(str(item.get("text", "")), locale=locale)
            entities.append(
                UIEntity(
                    entity_id=str(item.get("entity_id", "")),
                    label=str(item.get("label", "")),
                    role=str(item.get("role", "")),
                    text=normalized_text,
                    bbox=BBox(
                        x=int(item.get("x", 0)),
                        y=int(item.get("y", 0)),
                        width=int(item.get("width", 0)),
                        height=int(item.get("height", 0)),
                    ),
                    confidence=float(item.get("confidence", 0.0)),
                )
            )
        deduped = deduplicate_entities(entities)
        filtered = apply_role_thresholds(deduped, thresholds=role_thresholds)
        self._cache.set(cache_key, filtered)
        return filtered


def _build_payload(screenshot: bytes, task_hint: str) -> dict[str, Any]:
    encoded = base64.b64encode(screenshot).decode("ascii")
    return {
        "inputs": [
            {"name": "screenshot_base64", "datatype": "BYTES", "shape": [1], "data": [encoded]},
            {"name": "task_hint", "datatype": "BYTES", "shape": [1], "data": [task_hint]},
        ]
    }
