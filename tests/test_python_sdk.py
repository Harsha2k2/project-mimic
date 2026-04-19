import json

import httpx
import pytest

from project_mimic_sdk import ProjectMimicClient, ProjectMimicSDKError


def test_python_sdk_create_session_sends_expected_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["api_key"] = request.headers.get("x-api-key")
        captured["tenant"] = request.headers.get("x-tenant-id")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, request=request, json={"session_id": "session-1"})

    transport = httpx.MockTransport(handler)
    with ProjectMimicClient(
        base_url="http://localhost:8000",
        api_key="sdk-key",
        tenant_id="tenant-a",
        transport=transport,
    ) as client:
        response = client.create_session(goal="sdk-goal", max_steps=7)

    assert response["session_id"] == "session-1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/sessions"
    assert captured["api_key"] == "sdk-key"
    assert captured["tenant"] == "tenant-a"
    assert captured["body"] == {"goal": "sdk-goal", "max_steps": 7}


def test_python_sdk_step_session_posts_action_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, request=request, json={"done": False, "info": {}, "observation": {}, "reward": {}})

    transport = httpx.MockTransport(handler)
    with ProjectMimicClient(base_url="http://localhost:8000", transport=transport) as client:
        client.step_session("session-2", action_type="click", target="search", metadata={"source": "sdk"})

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/sessions/session-2/step"
    assert captured["body"] == {"action_type": "click", "metadata": {"source": "sdk"}, "target": "search"}


def test_python_sdk_raises_typed_error_on_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request, json={"detail": "forbidden"})

    transport = httpx.MockTransport(handler)
    with ProjectMimicClient(base_url="http://localhost:8000", transport=transport) as client:
        with pytest.raises(ProjectMimicSDKError, match="status 403"):
            client.rollback_session("session-3")
