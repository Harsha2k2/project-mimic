"""Triton HTTP client adapter for vision inference."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from .grounding import BBox, UIEntity


class TritonInferenceError(RuntimeError):
    """Raised when Triton inference fails or returns invalid payloads."""


@dataclass(frozen=True)
class TritonConfig:
    endpoint: str
    model_name: str
    timeout_s: float = 5.0


class TritonVisionClient:
    """Small HTTP adapter for Triton infer endpoint."""

    def __init__(self, config: TritonConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout_s)

    def infer(self, screenshot: bytes, task_hint: str = "") -> dict[str, Any]:
        payload = _build_payload(screenshot=screenshot, task_hint=task_hint)
        url = f"{self.config.endpoint}/v2/models/{self.config.model_name}/infer"
        response = self._client.post(url, json=payload)

        if response.status_code >= 400:
            raise TritonInferenceError(f"triton error status={response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise TritonInferenceError("triton returned non-json response") from exc

        if "entities" not in data:
            raise TritonInferenceError("triton response missing entities")

        return data

    def infer_entities(self, screenshot: bytes, task_hint: str = "") -> list[UIEntity]:
        raw = self.infer(screenshot=screenshot, task_hint=task_hint)
        entities = []
        for item in raw.get("entities", []):
            entities.append(
                UIEntity(
                    entity_id=str(item.get("entity_id", "")),
                    label=str(item.get("label", "")),
                    role=str(item.get("role", "")),
                    text=str(item.get("text", "")),
                    bbox=BBox(
                        x=int(item.get("x", 0)),
                        y=int(item.get("y", 0)),
                        width=int(item.get("width", 0)),
                        height=int(item.get("height", 0)),
                    ),
                    confidence=float(item.get("confidence", 0.0)),
                )
            )
        return entities


def _build_payload(screenshot: bytes, task_hint: str) -> dict[str, Any]:
    encoded = base64.b64encode(screenshot).decode("ascii")
    return {
        "inputs": [
            {"name": "screenshot_base64", "datatype": "BYTES", "shape": [1], "data": [encoded]},
            {"name": "task_hint", "datatype": "BYTES", "shape": [1], "data": [task_hint]},
        ]
    }
