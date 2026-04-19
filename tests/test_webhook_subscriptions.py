from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.webhooks import JsonFileWebhookSubscriptionStore, LifecycleEventWebhookPublisher


def test_event_subscription_routes_require_admin_role(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,admin-key:admin")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/events/subscriptions",
        headers={"X-API-Key": "viewer-key"},
        json={
            "name": "viewer-sub",
            "callback_url": "https://example.invalid/hook",
            "events": ["session.create"],
        },
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/v1/events/subscriptions",
        headers={"X-API-Key": "admin-key"},
        json={
            "name": "admin-sub",
            "callback_url": "https://example.invalid/hook",
            "events": ["session.create"],
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["name"] == "admin-sub"
    assert payload["events"] == ["session.create"]

    listed = client.get(
        "/api/v1/events/subscriptions",
        headers={"X-API-Key": "admin-key"},
    )
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1


def test_session_create_emits_matching_webhook_event(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_post(url: str, json=None, headers=None, timeout=None):
        captured.append(
            {
                "url": url,
                "json": json,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json={"ok": True})

    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    monkeypatch.setattr("project_mimic.webhooks.httpx.post", fake_post)

    client = TestClient(create_app())

    subscribe = client.post(
        "/api/v1/events/subscriptions",
        headers={"X-API-Key": "admin-key"},
        json={
            "name": "session-create-sub",
            "callback_url": "https://example.invalid/create",
            "events": ["session.create"],
        },
    )
    assert subscribe.status_code == 200

    created = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "admin-key"},
        json={"goal": "emit-webhook", "max_steps": 2},
    )
    assert created.status_code == 200

    assert len(captured) == 1
    envelope = captured[0]["json"]
    assert isinstance(envelope, dict)
    assert envelope["event_type"] == "session.create"
    assert envelope["payload"]["session_id"] == created.json()["session_id"]
    assert captured[0]["headers"]["X-Project-Mimic-Event"] == "session.create"


def test_non_matching_subscription_event_is_not_delivered(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_post(url: str, json=None, headers=None, timeout=None):
        captured.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json={"ok": True})

    monkeypatch.setenv("API_AUTH_KEYS", "admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin")
    monkeypatch.setattr("project_mimic.webhooks.httpx.post", fake_post)

    client = TestClient(create_app())

    subscribe = client.post(
        "/api/v1/events/subscriptions",
        headers={"X-API-Key": "admin-key"},
        json={
            "name": "rollback-only",
            "callback_url": "https://example.invalid/rollback",
            "events": ["session.rollback"],
        },
    )
    assert subscribe.status_code == 200

    created = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "admin-key"},
        json={"goal": "no-delivery", "max_steps": 2},
    )
    assert created.status_code == 200

    assert captured == []


def test_json_file_subscription_store_round_trips(tmp_path: Path) -> None:
    store_path = tmp_path / "subscriptions.json"
    store = JsonFileWebhookSubscriptionStore(str(store_path))
    publisher = LifecycleEventWebhookPublisher(store=store)

    created = publisher.create_subscription(
        name="persisted",
        callback_url="https://example.invalid/persisted",
        events=["session.create"],
        tenant_id="tenant-a",
    )

    reloaded = LifecycleEventWebhookPublisher(store=store)
    listed = reloaded.list_subscriptions(tenant_id="tenant-a")
    assert len(listed) == 1
    assert listed[0]["subscription_id"] == created["subscription_id"]
