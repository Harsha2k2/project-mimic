from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_review_queue_submit_list_and_resolve_flow() -> None:
    client = TestClient(create_app())

    submitted = client.post(
        "/api/v1/reviews/queue",
        json={
            "session_id": "session-1",
            "action_payload": {"action_type": "click", "target": "buy"},
            "confidence": 0.41,
            "reason": "low confidence on call-to-action",
        },
    )
    assert submitted.status_code == 200
    item = submitted.json()
    assert item["status"] == "pending"

    listed = client.get("/api/v1/reviews/queue", params={"status": "pending"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1

    resolved = client.post(
        f"/api/v1/reviews/queue/{item['review_id']}/resolve",
        json={"decision": "approved", "note": "reviewed by operator"},
    )
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    assert resolved_payload["status"] == "approved"
    assert resolved_payload["resolution_note"] == "reviewed by operator"


def test_review_queue_rejects_resolving_item_twice() -> None:
    client = TestClient(create_app())

    submitted = client.post(
        "/api/v1/reviews/queue",
        json={
            "action_payload": {"action_type": "type", "text": "hello"},
            "confidence": 0.3,
            "reason": "intent ambiguity",
        },
    )
    assert submitted.status_code == 200
    review_id = submitted.json()["review_id"]

    first = client.post(
        f"/api/v1/reviews/queue/{review_id}/resolve",
        json={"decision": "rejected", "note": "unsafe action"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/reviews/queue/{review_id}/resolve",
        json={"decision": "approved", "note": "retry"},
    )
    assert second.status_code == 409


def test_review_queue_is_tenant_scoped(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "key-a,key-b")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "key-a:operator,key-b:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "key-a:tenant-a,key-b:tenant-b")

    client = TestClient(create_app())

    tenant_a_item = client.post(
        "/api/v1/reviews/queue",
        headers={"X-API-Key": "key-a"},
        json={"action_payload": {"action_type": "click"}, "confidence": 0.2, "reason": "needs review"},
    )
    tenant_b_item = client.post(
        "/api/v1/reviews/queue",
        headers={"X-API-Key": "key-b"},
        json={"action_payload": {"action_type": "type"}, "confidence": 0.2, "reason": "needs review"},
    )
    assert tenant_a_item.status_code == 200
    assert tenant_b_item.status_code == 200

    list_a = client.get("/api/v1/reviews/queue", headers={"X-API-Key": "key-a"})
    assert list_a.status_code == 200
    ids_a = {item["review_id"] for item in list_a.json()["items"]}

    assert tenant_a_item.json()["review_id"] in ids_a
    assert tenant_b_item.json()["review_id"] not in ids_a


def test_legacy_review_queue_routes_emit_deprecation_headers() -> None:
    client = TestClient(create_app())

    submitted = client.post(
        "/reviews/queue",
        json={"action_payload": {"action_type": "wait"}, "confidence": 0.4, "reason": "legacy path"},
    )
    assert submitted.status_code == 200
    assert submitted.headers.get("Deprecation") == "true"
    review_id = submitted.json()["review_id"]

    listed = client.get("/reviews/queue")
    assert listed.status_code == 200
    assert listed.headers.get("Deprecation") == "true"

    resolved = client.post(
        f"/reviews/queue/{review_id}/resolve",
        json={"decision": "approved", "note": "legacy resolve"},
    )
    assert resolved.status_code == 200
    assert resolved.headers.get("Deprecation") == "true"
