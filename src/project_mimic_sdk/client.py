"""Python SDK client for Project Mimic control-plane APIs."""

from __future__ import annotations

import json
from typing import Any

import httpx


class ProjectMimicSDKError(RuntimeError):
    """Raised when the SDK cannot complete an API operation."""


class ProjectMimicClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        tenant_id: str | None = None,
        api_prefix: str = "/api/v1",
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")

        normalized_prefix = api_prefix.strip() or "/api/v1"
        if not normalized_prefix.startswith("/"):
            normalized_prefix = f"/{normalized_prefix}"

        self._api_prefix = normalized_prefix.rstrip("/")

        headers: dict[str, str] = {}
        if api_key and api_key.strip():
            headers["X-API-Key"] = api_key.strip()
        if tenant_id and tenant_id.strip():
            headers["X-Tenant-ID"] = tenant_id.strip()

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ProjectMimicClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def create_session(self, *, goal: str, max_steps: int = 20) -> dict[str, Any]:
        payload = {
            "goal": goal,
            "max_steps": max_steps,
        }
        return self._request("POST", "/sessions", json_body=payload)

    def step_session(
        self,
        session_id: str,
        *,
        action_type: str,
        target: str | None = None,
        text: str | None = None,
        x: int | None = None,
        y: int | None = None,
        wait_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action_type": action_type,
            "metadata": metadata or {},
        }
        if target is not None:
            payload["target"] = target
        if text is not None:
            payload["text"] = text
        if x is not None:
            payload["x"] = x
        if y is not None:
            payload["y"] = y
        if wait_ms is not None:
            payload["wait_ms"] = wait_ms

        return self._request("POST", f"/sessions/{session_id}/step", json_body=payload)

    def session_state(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}/state")

    def list_sessions(
        self,
        *,
        status: str | None = None,
        goal_contains: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if status is not None:
            params["status"] = status
        if goal_contains is not None:
            params["goal_contains"] = goal_contains
        return self._request("GET", "/sessions", params=params)

    def restore_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}/restore")

    def rollback_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/rollback")

    def resume_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/resume")

    def operator_snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/operator/snapshot")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                f"{self._api_prefix}{path}",
                json=json_body,
                params=params,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._response_detail(exc.response)
            raise ProjectMimicSDKError(
                f"request failed with status {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProjectMimicSDKError(f"request failed: {exc}") from exc

        if not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProjectMimicSDKError(f"response is not valid JSON: {response.text}") from exc

        if not isinstance(payload, dict):
            raise ProjectMimicSDKError("response JSON payload must be an object")
        return payload

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        return json.dumps(payload, sort_keys=True)
