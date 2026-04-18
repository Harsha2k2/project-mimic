from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_create_session_and_get_state() -> None:
    client = TestClient(create_app())

    create_response = client.post("/api/v1/sessions", json={"goal": "find flights", "max_steps": 5})
    assert create_response.status_code == 200

    payload = create_response.json()
    session_id = payload["session_id"]
    assert payload["observation"]["status"] == "running"

    state_response = client.get(f"/api/v1/sessions/{session_id}/state")
    assert state_response.status_code == 200
    assert state_response.json()["goal"] == "find flights"


def test_step_endpoint_returns_reward_and_done_flag() -> None:
    client = TestClient(create_app())
    create_response = client.post("/api/v1/sessions", json={"goal": "find flights", "max_steps": 1})
    session_id = create_response.json()["session_id"]

    step_response = client.post(
        f"/api/v1/sessions/{session_id}/step",
        json={"action_type": "click", "target": "search"},
    )

    assert step_response.status_code == 200
    step_payload = step_response.json()
    assert step_payload["reward"]["score"] > 0.0
    assert step_payload["done"] is True


def test_unknown_session_returns_404() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/sessions/missing/state")
    assert response.status_code == 404


def test_reset_endpoint_allows_goal_override() -> None:
    client = TestClient(create_app())
    create_response = client.post("/api/v1/sessions", json={"goal": "initial goal", "max_steps": 2})
    session_id = create_response.json()["session_id"]

    reset_response = client.post(f"/api/v1/sessions/{session_id}/reset", json={"goal": "updated goal"})
    assert reset_response.status_code == 200
    assert reset_response.json()["goal"] == "updated goal"


def test_decision_click_returns_best_target() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/decision/click",
        json={
            "entities": [
                {
                    "entity_id": "e1",
                    "label": "Search",
                    "role": "button",
                    "text": "Search Flights",
                    "confidence": 0.9,
                    "bbox": {"x": 100, "y": 100, "width": 120, "height": 40},
                }
            ],
            "dom_nodes": [
                {
                    "dom_node_id": "search-btn",
                    "role": "button",
                    "text": "Search Flights",
                    "visible": True,
                    "enabled": True,
                    "z_index": 10,
                    "bbox": {"x": 102, "y": 101, "width": 120, "height": 40},
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["dom_node_id"] == "search-btn"


def test_decision_click_returns_no_target_for_non_interactable_dom() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/decision/click",
        json={
            "entities": [
                {
                    "entity_id": "e1",
                    "label": "Search",
                    "role": "button",
                    "text": "Search",
                    "confidence": 0.9,
                    "bbox": {"x": 100, "y": 100, "width": 80, "height": 30},
                }
            ],
            "dom_nodes": [
                {
                    "dom_node_id": "search-btn",
                    "role": "button",
                    "text": "Search",
                    "visible": False,
                    "enabled": True,
                    "z_index": 1,
                    "bbox": {"x": 100, "y": 100, "width": 80, "height": 30},
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_target"


def test_metrics_endpoint_tracks_requests() -> None:
    client = TestClient(create_app())

    create = client.post("/api/v1/sessions", json={"goal": "metrics check", "max_steps": 2})
    assert create.status_code == 200

    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()

    assert "/api/v1/sessions" in payload["requests"]
    assert payload["requests"]["/api/v1/sessions"] >= 1
    assert "200" in payload["status_codes"]


def test_restore_endpoint_returns_checkpoint_payload() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/sessions", json={"goal": "restore-check", "max_steps": 3})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    client.post(f"/api/v1/sessions/{session_id}/step", json={"action_type": "click", "target": "search"})
    restored = client.get(f"/api/v1/sessions/{session_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["state"]["step_index"] >= 0


def test_list_sessions_endpoint_returns_paged_result() -> None:
    client = TestClient(create_app())
    client.post("/api/v1/sessions", json={"goal": "list-check", "max_steps": 3})

    response = client.get("/api/v1/sessions?page=1&page_size=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total"] >= 1


def test_legacy_endpoint_emits_deprecation_headers() -> None:
    client = TestClient(create_app())

    response = client.post("/sessions", json={"goal": "legacy", "max_steps": 2})
    assert response.status_code == 200
    assert response.headers.get("Deprecation") == "true"
    assert response.headers.get("Sunset")


def test_request_id_is_propagated_in_success_response() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/sessions",
        headers={"X-Request-ID": "req-123"},
        json={"goal": "request-id", "max_steps": 2},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-123"
    assert response.headers.get("X-Correlation-ID") == "req-123"


def test_structured_error_contract_contains_machine_code() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/sessions/missing/state", headers={"X-Request-ID": "err-777"})
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "SESSION_NOT_FOUND"
    assert payload["error"]["correlation_id"] == "err-777"


def test_list_sessions_supports_goal_filter_and_sort() -> None:
    client = TestClient(create_app())
    client.post("/api/v1/sessions", json={"goal": "flight search one", "max_steps": 3})
    client.post("/api/v1/sessions", json={"goal": "hotel booking", "max_steps": 3})

    response = client.get("/api/v1/sessions?goal_contains=flight&sort_by=created_at&sort_order=asc")
    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["goal_contains"] == "flight"
    assert all("flight" in item["goal"].lower() for item in payload["items"])


def test_openapi_contains_decision_endpoint_examples() -> None:
    client = TestClient(create_app())
    schema = client.get("/openapi.json")
    assert schema.status_code == 200

    paths = schema.json()["paths"]
    assert "/api/v1/decision/click" in paths
    response_example = paths["/api/v1/decision/click"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["example"]
    assert response_example["status"] == "ok"


def test_api_auth_blocks_protected_routes_when_key_missing(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "alpha-key")
    client = TestClient(create_app())

    response = client.post("/api/v1/sessions", json={"goal": "auth-check", "max_steps": 2})
    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "UNAUTHORIZED"


def test_api_auth_allows_valid_key(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "alpha-key")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "alpha-key"},
        json={"goal": "auth-check", "max_steps": 2},
    )
    assert response.status_code == 200


def test_api_auth_does_not_block_openapi(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "alpha-key")
    client = TestClient(create_app())

    response = client.get("/openapi.json")
    assert response.status_code == 200


def test_api_rbac_blocks_viewer_from_mutating_routes(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator")
    client = TestClient(create_app())

    blocked = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "viewer-key"},
        json={"goal": "rbac", "max_steps": 2},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "FORBIDDEN"


def test_api_rbac_allows_viewer_read_only_routes(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator")
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "operator-key"},
        json={"goal": "rbac", "max_steps": 2},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    allowed = client.get(
        f"/api/v1/sessions/{session_id}/state",
        headers={"X-API-Key": "viewer-key"},
    )
    assert allowed.status_code == 200


def test_tenant_isolation_blocks_cross_tenant_state_access(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "tenant-a-key,tenant-b-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "tenant-a-key:operator,tenant-b-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "tenant-a-key:tenant-a,tenant-b-key:tenant-b")
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "tenant-a-key"},
        json={"goal": "tenant-a-session", "max_steps": 3},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    denied = client.get(
        f"/api/v1/sessions/{session_id}/state",
        headers={"X-API-Key": "tenant-b-key"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_tenant_isolation_filters_session_listing(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "tenant-a-key,tenant-b-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "tenant-a-key:operator,tenant-b-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "tenant-a-key:tenant-a,tenant-b-key:tenant-b")
    client = TestClient(create_app())

    response_a = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "tenant-a-key"},
        json={"goal": "tenant-a", "max_steps": 2},
    )
    response_b = client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": "tenant-b-key"},
        json={"goal": "tenant-b", "max_steps": 2},
    )
    assert response_a.status_code == 200
    assert response_b.status_code == 200

    listed = client.get("/api/v1/sessions", headers={"X-API-Key": "tenant-a-key"})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items
    assert all(item["tenant_id"] == "tenant-a" for item in items)
