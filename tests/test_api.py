from fastapi.testclient import TestClient

from project_mimic.api import create_app


def test_create_session_and_get_state() -> None:
    client = TestClient(create_app())

    create_response = client.post("/sessions", json={"goal": "find flights", "max_steps": 5})
    assert create_response.status_code == 200

    payload = create_response.json()
    session_id = payload["session_id"]
    assert payload["observation"]["status"] == "running"

    state_response = client.get(f"/sessions/{session_id}/state")
    assert state_response.status_code == 200
    assert state_response.json()["goal"] == "find flights"


def test_step_endpoint_returns_reward_and_done_flag() -> None:
    client = TestClient(create_app())
    create_response = client.post("/sessions", json={"goal": "find flights", "max_steps": 1})
    session_id = create_response.json()["session_id"]

    step_response = client.post(
        f"/sessions/{session_id}/step",
        json={"action_type": "click", "target": "search"},
    )

    assert step_response.status_code == 200
    step_payload = step_response.json()
    assert step_payload["reward"]["score"] > 0.0
    assert step_payload["done"] is True


def test_unknown_session_returns_404() -> None:
    client = TestClient(create_app())
    response = client.get("/sessions/missing/state")
    assert response.status_code == 404


def test_reset_endpoint_allows_goal_override() -> None:
    client = TestClient(create_app())
    create_response = client.post("/sessions", json={"goal": "initial goal", "max_steps": 2})
    session_id = create_response.json()["session_id"]

    reset_response = client.post(f"/sessions/{session_id}/reset", json={"goal": "updated goal"})
    assert reset_response.status_code == 200
    assert reset_response.json()["goal"] == "updated goal"
